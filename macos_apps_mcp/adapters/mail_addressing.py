"""Mail addressing — the ONE module that knows how to NAME a message, a mailbox or an
account (#155).

Module shape, for #159/#78/#80/#140/#153/#81 to build on: everything here answers "which
message/mailbox/account does this token mean?", and nothing here reads a body, sends, or
decides policy. Three layers, cheapest first:

- **id forms** — ``bare_id`` (what AppleScript's ``message id`` reports and every
  id-taking script wants) and ``stored_id`` (what the Envelope Index stores, bracketed).
  These are the ONLY sanctioned id conversions; the concept used to live in seven inline
  ``.lstrip("<").rstrip(">")`` copies plus ``_norm_mid`` plus ``thread()``'s
  re-bracketing, which is how the two planes silently stopped matching each other. The
  third id form — the ``message://`` citation — stays in ``mail_index._deeplink``
  because ``row_to_pointer`` needs it and this module must not become an import that
  store depends on.
- **mailbox** — ``validate_mailbox`` (the five canonical names), ``mailbox_args`` (a
  round-trip ``folder`` token → the argv pair the shared ``MAILBOX_REF`` AppleScript
  handler takes) and ``resolve_mailbox`` (a human NAME → exact urls). ``MAILBOX_REF``
  itself lives here too: it is the AppleScript half of the same question, and keeping it
  next to its Python inverse is what stops the two drifting.
- **account** — ``resolve_account`` (name/uuid/"On My Mac" → the uuid mailboxes.url
  embeds), over the cached ``account_map`` and ``local_account_id``.

On top of them, ``resolve(message_id, folder=None, account=None) -> ResolvedMessage`` is
the one entry point a caller with a bare id needs: it answers with EXACTLY ONE target or
raises. Every 0.9.2+ write (move, trash, dedupe, save-attachment) needs that rule, and
inherits it by calling this instead of re-deriving it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import unquote

from ..errors import AmbiguousTarget, NativeError
from ..runtime import run_osascript
from ..text import RS, STRIP_FRAMING, US
from . import mail_index

# --- id forms ------------------------------------------------------------------------


def bare_id(message_id: str) -> str:
    """A Message-ID in the form AppleScript reports and every id-taking script wants:
    no angle brackets, no surrounding whitespace. Accepts either form, so a caller
    passing back a bracketed id from the index resolves instead of failing loudly."""
    return message_id.strip().lstrip("<").rstrip(">").strip()


def stored_id(message_id: str) -> str:
    """A Message-ID in the form the Envelope Index stores: angle-bracketed.

    The two planes disagree by construction — sqlite keeps ``<a@b>``, AppleScript's
    ``message id`` reports ``a@b`` — so an id crossing from a Mail read into an indexed
    query matched zero rows and looked exactly like a genuine miss."""
    return f"<{bare_id(message_id)}>"


# --- mailbox -------------------------------------------------------------------------

# Canonical system-mailbox names a mailbox-scoped operation accepts. Mailbox
# resolution uses Mail's UNIFIED, locale-independent accessors (`inbox`/`sent
# mailbox`/…, see MAILBOX_REF), so only the canonical name matters — the
# per-locale name tables from #61 died with the unified-accessor migration.
SYSTEM_MAILBOXES = frozenset({"inbox", "sent", "drafts", "trash", "junk"})


def validate_mailbox(mailbox: str) -> str:
    """Canonical lowercase system-mailbox name (inbox/sent/drafts/trash/junk), for the
    unified accessors in the scripts. Raises on an unknown name so a typo fails loudly
    rather than resolving to the wrong mailbox."""
    canon = mailbox.strip().lower()
    if canon not in SYSTEM_MAILBOXES:
        raise ValueError(
            f"unknown mailbox {mailbox!r} — pass the `folder` value from a mail_search "
            "result back VERBATIM (an imap:// url; it is an opaque token, not a name), "
            f"or one of {sorted(SYSTEM_MAILBOXES)}. Do not retry with a folder name."
        )
    return canon


def mailbox_args(mailbox: str) -> tuple[str, str]:
    """``(account-id, mailbox path)`` argv pair for the shared ``mailboxFor`` handler —
    the INVERSE of ``resolve_mailbox`` (#146).

    ``mailbox`` is a search result's ``folder`` value passed back verbatim: the raw
    percent-encoded mailboxes.url (``imap://<account-uuid>/%5BGmail%5D/Spam``). It is an
    opaque ROUND-TRIP TOKEN, deliberately not a human-readable name — requiring a name
    would hand #144's encoding mismatch (``%5BGmail%5D`` vs ``[Gmail]``) back to the
    caller, and the url's account segment also makes same-named folders under two
    accounts, and the same Message-ID living in several mailboxes, unambiguous by
    construction.

    Device-verified 2026-07-31: ``mailbox "[Gmail]/Spam" of account …`` resolves and the
    encoded spelling does not — so the path is DECODED here, exactly as
    ``resolve_mailbox`` decodes before matching. The On My Mac store gets the
    ``"local"`` sentinel instead of its UUID: Mail's ``every account`` never lists it
    (see ``overview()``), so those mailboxes hang off the application itself. A UUID can
    never collide with that sentinel.

    The five special names (inbox/sent/drafts/trash/junk) are still accepted as an alias
    layer — an empty account id selects Mail's unified accessors — so ``mailbox`` reads
    the same everywhere and mail_attachments' existing vocabulary keeps working.
    """
    value = mailbox.strip()
    if not value:
        raise ValueError(
            "this call needs a mailbox — pass the `folder` value from the mail_search "
            "result that produced this message id, verbatim"
        )
    scheme, sep, rest = value.partition("://")
    if not sep:
        return "", validate_mailbox(value)
    account, _, path = rest.partition("/")
    if not account:
        raise ValueError(f"mailbox url {mailbox!r} names no account")
    path = unquote(path)
    if not path:
        raise ValueError(f"mailbox url {mailbox!r} names no mailbox")
    return ("local" if scheme.lower() == "local" else account), path


def is_mailbox_url(mailbox: str) -> bool:
    """True when ``mailbox`` is a round-trip url token rather than a typed name.

    The distinction is what #156(2) turns on: a url was a REAL handle when it was
    issued, so a url that now resolves to nothing is stale (a message moved out from
    under it) and stays a 0-hit read; a name is something a model typed from memory,
    so a name that resolves to nothing is a followable error."""
    return "://" in mailbox


def resolve_mailbox(name: str, account: str | None = None) -> list[str]:
    """Raw mailboxes.url values whose DECODED path contains ``name`` (#144).

    The one mailbox vocabulary: ``mail_overview`` reports the decoded name
    ("Junk E-mail"), the url stores the encoded one ("Junk%20E-mail"), and matching
    happened against the encoded side — so feeding overview's own output back into
    a search returned 0 hits for every name that encodes. Match decoded-vs-decoded:
    the NEEDLE is unquoted too, so the encoded spelling models already learned
    keeps resolving. Case-insensitive substring — today's semantics, kept on
    purpose (a pure bug fix, not a stricter matcher). Decoding cannot happen in SQL
    (no urldecode, and Mail's encoding is not reproducible by ``quote()``), which
    is why this is an adapter helper feeding exact urls to the query, not a LIKE.

    A ``name`` that is itself a round-trip URL is matched EXACTLY instead (account
    segment + decoded path), not as a substring. Every mail read hands back ``folder``
    as such a url and documents it as the token to pass back verbatim — but a url is
    never a substring of a bare mailbox PATH, so feeding a read's own output straight
    into ``mail_search(mailbox=…)`` matched zero rows and looked exactly like an empty
    mailbox (found 2026-08-03 by an integration fixture doing precisely what the
    docstrings tell a caller to do). Decoded on both sides for #144's reason, and
    because ``create_mailbox`` synthesises a token Mail later re-spells with ``%20``:
    the two are not byte-equal and must still name one mailbox.

    ``account`` (name or UUID) restricts to that account's mailboxes. Reads take
    every match; the 0.9.2 write tools reuse this and demand exactly one.
    """
    account_uuid = resolve_account(account).casefold() if account else None
    want_uuid = want_path = None
    if is_mailbox_url(name):
        _, _, rest = name.strip().partition("://")
        want_uuid, _, raw_path = rest.partition("/")
        want_uuid, want_path = want_uuid.casefold(), unquote(raw_path).casefold()
    needle = unquote(name).casefold()
    out = []
    for url in mail_index.query_mailbox_urls():
        _, _, rest = url.partition("://")
        uuid, _, path = rest.partition("/")
        if account_uuid and uuid.casefold() != account_uuid:
            continue
        decoded = unquote(path).casefold()
        if want_uuid is not None:
            if uuid.casefold() == want_uuid and decoded == want_path:
                out.append(url)
        elif needle in decoded:
            out.append(url)
    return out


# The ONE mailbox resolver (#146): every id-addressed script composes this handler and
# calls `my mailboxFor(acct, path)` instead of naming a mailbox itself. Both arguments
# come from mailbox_args via argv (no interpolation).
#
# It exists as a shared handler precisely because the bug it fixes was SEVEN copies of
# `messages of inbox` drifting apart from the read plane: #62 scoped the body path to
# the inbox when the reads were inbox-only too, then #70/#75 widened search to every
# mailbox and nobody re-read the six copies of the old premise. One resolver, one place
# to widen.
#
# It carries its OWN `with timeout` (#56): AppleScript's timeout is lexical, so the
# caller's wrapper does not cover a handler body called from inside it.
#
# Device-verified 2026-07-31, all branches: "" -> the unified accessors (inbox 27 msgs,
# drafts 15); "local" -> `mailbox "Outbox"` off the application (the On My Mac store,
# which `every account` never lists); a UUID -> `mailbox "[Gmail]/Spam" of account …`
# (80 msgs), with the path DECODED — the encoded "%5BGmail%5D/Spam" does not resolve.
# Both miss paths raise loudly rather than falling back to some other mailbox: an
# unknown folder gives "Can't get mailbox "Nope" of account …", an unknown account
# "Can't get account 1 whose id = …". The reference returned survives the handler's tell
# boundary and is usable in the caller's own tell block (verified against a real filed
# message).
MAILBOX_REF = """on mailboxFor(acctId, mbPath)
  with timeout of 120 seconds
  tell application "Mail"
    if acctId is "" then
      if mbPath is "inbox" then
        return inbox
      else if mbPath is "sent" then
        return sent mailbox
      else if mbPath is "drafts" then
        return drafts mailbox
      else if mbPath is "trash" then
        return trash mailbox
      else if mbPath is "junk" then
        return junk mailbox
      else
        error "unknown system mailbox " & mbPath
      end if
    else if acctId is "local" then
      return mailbox mbPath
    else
      return mailbox mbPath of (first account whose id is acctId)
    end if
  end tell
  end timeout
end mailboxFor"""


# --- account -------------------------------------------------------------------------

# Account UUID -> display name. The UUID is what mailboxes.url embeds; the name is
# what a human reads. Device-verified: AppleScript `id of account` returns exactly
# the UUID in mailboxes.url. There is NO at-rest source — MailData has no accounts
# plist, and ~/Library/Accounts/Accounts4.sqlite omits some accounts' description
# entirely (iCloud is blank on this Mac), so it would cost an FDA grant, a
# fingerprint and a fallback for a cosmetic label. Cached per process: accounts
# change about never. with timeout (#56): bound the Apple Events so an orphaned
# osascript can't pin Mail.
_ACCOUNT_MAP_CACHE: dict[str, str] | None = None

# monotonic() timestamp of the most recently cached FAILURE-OR-EMPTY result, or None
# when the cache is unpopulated or holds a non-empty success. An exit-0 run that
# returned no account records is leashed exactly like a failure: Mail still launching
# at login can answer with an empty list, and a genuine zero-account Mac merely
# re-probes once per TTL — while caching that empty forever reproduced the 872767d
# symptom through the success branch. Compared with time.monotonic(), never wall-clock
# (must not break when the clock changes — NTP sync, sleep/wake, DST).
_ACCOUNT_MAP_FAILURE_AT: float | None = None

# This adapter ships inside a launchd agent running daemon.serve() — a process that can
# live for DAYS. The daemon can start at login before Mail has finished launching, or
# while an Automation (TCC) prompt is still unanswered on screen; both can flip to
# "working" long after that first failed lookup, without the daemon ever restarting.
# Caching a failure forever (as the success cache does, correctly, below) would leave
# mail_overview showing raw UUIDs and mail_search(account=...) raising for the rest of
# the daemon's life, cured only by a restart. So a failure gets a short leash instead:
# remember it for this long, then allow exactly one more attempt.
_ACCOUNT_MAP_FAILURE_TTL = 60.0  # seconds

_ACCOUNTS = (
    STRIP_FRAMING
    + """

on run argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    repeat with acct in every account
      set out to out & (id of acct) & us & (name of acct) & rs
    end repeat
  end tell
  end timeout
  return out
end run
"""
)


def account_map() -> dict[str, str]:
    """UUID -> account display name, cached. ``{}`` when Mail is unreachable — this is a
    label lookup, and it must never fail a call whose real payload came from sqlite.

    The FAILURE is cached too, not just the success: on a machine where Automation is
    denied, an uncached failure re-spawns osascript on EVERY call, and Python kills
    each spawn only at ``runtime._OSASCRIPT_TIMEOUT`` (30s) — a 30-second stall per
    call on tools advertised as fast. But a failure is cached only for
    ``_ACCOUNT_MAP_FAILURE_TTL`` seconds (see its comment): unlike the account list,
    whether Mail is running and whether Automation is granted can both change while
    this long-lived daemon keeps running, so a failure gets one more attempt after
    the TTL instead of being final
    for the process's whole lifetime. A non-empty success is still cached forever; an
    EMPTY success gets the same leash as a failure — Mail launching at login can
    return exit 0 with no records yet, and that transient cached forever is the same
    raw-UUIDs-until-restart bug the failure TTL exists to prevent.
    """
    global _ACCOUNT_MAP_CACHE, _ACCOUNT_MAP_FAILURE_AT
    if (
        _ACCOUNT_MAP_FAILURE_AT is not None
        and time.monotonic() - _ACCOUNT_MAP_FAILURE_AT >= _ACCOUNT_MAP_FAILURE_TTL
    ):
        # TTL elapsed: allow exactly one more attempt.
        _ACCOUNT_MAP_CACHE = None
        _ACCOUNT_MAP_FAILURE_AT = None
    if _ACCOUNT_MAP_CACHE is None:
        try:
            raw = run_osascript(_ACCOUNTS)
        except (NativeError, OSError):
            # Every osascript failure mode is one of these two and all mean the same
            # thing — no names available, never "the call failed". run_osascript raises
            # NativeError subclasses (AutomationDenied / AppNotRunning / NativeTimeout /
            # generic) on any script or exit failure, and Popen raises OSError when the
            # osascript binary itself is missing. Deliberately NOT a bare except: a bug
            # in the parsing below must surface, not be swallowed as "Mail unreachable".
            _ACCOUNT_MAP_CACHE = {}
            _ACCOUNT_MAP_FAILURE_AT = time.monotonic()
            return _ACCOUNT_MAP_CACHE
        out = {}
        for rec in raw.split(RS):
            if US in rec:
                uuid, name = rec.split(US, 1)
                if uuid.strip():
                    out[uuid.strip()] = name.strip()
        _ACCOUNT_MAP_CACHE = out
        _ACCOUNT_MAP_FAILURE_AT = None if out else time.monotonic()
    return _ACCOUNT_MAP_CACHE


# mailboxes.url embeds the account as a plain RFC-4122 UUID (8-4-4-4-12 hex).
_ACCOUNT_UUID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.IGNORECASE
)

# What overview() prints for the local:// store (see MailAdapter.overview's docstring).
# A single constant so the two can't drift apart again — the whole point of N1 was that
# mail_overview started reporting this name while mail_search still rejected it.
ON_MY_MAC = "On My Mac"

# resolve_account's accepted local-store spellings, matched case-insensitively:
# ON_MY_MAC itself (what overview() actually prints) plus "local" as a shorter alias.
_LOCAL_ACCOUNT_ALIASES = frozenset({ON_MY_MAC.casefold(), "local"})


def local_account_id() -> str | None:
    """The account segment mailboxes.url embeds for the On My Mac store — the exact
    value build_header_query's ``account`` clause anchors on for a ``local://``
    mailbox. Read fresh from the Envelope Index (like overview()'s own read) rather
    than guessed or hard-coded: the id is device-specific and AppleScript never lists
    this store as an account, so there is no other source for it. None when there is
    no Envelope Index yet, or the index has no ``local://`` mailbox at all.
    """
    url = mail_index.query_local_account_url()
    if not url:
        return None
    # <scheme>://<UUID>/<path> — the UUID segment is what the account clause anchors
    # on. URL-shape parsing is Mail domain knowledge, so it stays here, not in the
    # store accessor.
    return mail_index.account_of(url)


def resolve_account(value: str) -> str:
    """A Mail account display name -> the UUID that mailboxes.url embeds.

    A value that already IS a UUID is returned untouched WITHOUT contacting Mail. That
    is what keeps the promise the read tools document: the name lookup runs osascript,
    which LAUNCHES Mail if it isn't running, so a tool that claims "no Mail launch"
    must have a path that doesn't take it — and the UUID path is that path.

    ``"On My Mac"`` (case-insensitive, ``"local"`` also accepted) resolves the local
    store the same way: read from the Envelope Index, never osascript — Mail's `every
    account` never lists it (see overview()'s docstring), so there is nothing for
    osascript to tell us anyway.

    An unresolvable name RAISES. Returning it unchanged handed a display name to a url
    match, where it degraded into a substring match over the whole mailbox path:
    ``account="Business"`` then matched any account's ``…/Business Docs`` folder and
    reported it as though the account filter had worked. A confident wrong answer is
    worse than a typed error naming the accounts that do exist.
    """
    value = value.strip()
    if _ACCOUNT_UUID_RE.match(value):
        return value
    if value.casefold() in _LOCAL_ACCOUNT_ALIASES:
        local_id = local_account_id()
        if local_id:
            return local_id
        raise NativeError(
            "no Mail data found (~/Library/Mail/V*/MailData/Envelope Index) or no "
            "On My Mac store in it. Open Mail once to create it. Do not retry."
        )
    names = account_map()
    matches = [
        uuid for uuid, name in names.items() if name.casefold() == value.casefold()
    ]
    if len(matches) > 1:
        # Same rule as the unresolvable case below: never a confident wrong answer.
        # First-match-wins picked whichever account Mail happened to list first.
        raise AmbiguousTarget(
            f"{len(matches)} Mail accounts are named {value!r} — macos-apps-mcp "
            "never auto-picks an ambiguous target. Pass one of these account UUIDs "
            f"instead: {', '.join(matches)} (or rename the accounts in Mail so the "
            "names are unique)."
        )
    if matches:
        return matches[0]
    known = (
        f"known accounts: {sorted(names.values())}"
        if names
        else "Mail could not be reached to list account names, so only an account "
        'UUID or "On My Mac" works right now'
    )
    raise NativeError(
        f"unknown Mail account {value!r} — {known}. Pass an account name exactly as "
        'Mail shows it (or "On My Mac" for the local store), or an account UUID. '
        "Do not retry."
    )


# --- the resolver ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedMessage:
    """Exactly one addressable message: the triple every read now emits, resolved.

    ``id``      bare form — what the id-taking AppleScript wants.
    ``folder``  round-trip mailbox token: a mailboxes.url, or one of the five canonical
                names when the caller named a unified accessor.
    ``account`` the owning account's uuid, or None when the folder is a unified
                accessor and the account genuinely is unknown (never guessed).
    """

    id: str
    folder: str
    account: str | None = None

    @property
    def mailbox_args(self) -> tuple[str, str]:
        """The argv pair for the shared ``mailboxFor`` handler."""
        return mailbox_args(self.folder)


def resolve(
    message_id: str, folder: str | None = None, account: str | None = None
) -> ResolvedMessage:
    """One message id -> EXACTLY ONE target, or a followable raise (#155).

    ``folder`` is the disambiguator, not a requirement: given, it is trusted verbatim
    (that is the round-trip contract, and it costs no query and no Full Disk Access —
    the path ``mail_body(id, mailbox)`` has always taken). Omitted, the id is resolved
    against the Envelope Index through ``build_header_query``'s ``message_ids`` filter,
    so a note that stored only the id — the correct pointers-not-payload thing to store
    — still reaches the message after #78's ``move_mail`` invalidated whatever folder
    token it once had.

    "Exactly one" is not a tie-break we invented here: the indexed query dedups by
    Message-ID and returns the RANKED copy (a live INBOX copy beats a filed copy beats
    an All Mail / Archive / Trash / Junk copy — see ``_MAILBOX_RANK``), which is the
    same copy every other read of this project cites. ``account`` narrows the lookup
    when the same id is filed under two accounts and the caller wants a specific one.

    The id-only path reads sqlite, so it needs Full Disk Access where the folder-given
    path needs only Automation. An id with no row raises rather than answering [] — a
    stored citation that no longer resolves is exactly the thing a caller must be told
    about, not a silent empty.
    """
    mid = bare_id(message_id)
    if not mid:
        raise ValueError("this call needs a message id")
    if folder:
        mailbox_args(folder)  # validate the token HERE, not deep inside a script
        return ResolvedMessage(mid, folder, mail_index.account_of(folder))
    hits = mail_index.query_search(
        message_ids=[stored_id(mid)],
        account=resolve_account(account) if account else None,
        limit=1,
    )
    if not hits:
        raise NativeError(
            f"no message with id {mid!r} in Mail's index"
            + (f" under account {account!r}" if account else "")
            + " — it may have been deleted, or never downloaded. Pass the `folder` "
            "value from the read that produced this id to address it directly. "
            "Do not retry with the same id alone."
        )
    hit = hits[0]
    return ResolvedMessage(mid, hit.folder or "", hit.account)
