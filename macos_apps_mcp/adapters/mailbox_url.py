"""The mailbox-url grammar in ONE place (#175): ``<scheme>://<uuid>/<encoded path>``.

Every mail read returns this token as ``folder`` and documents it as opaque — which
only holds if exactly one module does the string surgery. Before this file, eight
hand-parse sites and one hand-synthesis were spread over four modules, and the three
special-mailbox vocabularies had already drifted (the Bin gap: `_MAILBOX_RANK` ranked a
``Bin``-spelling account's trash as a *filed* copy, beating an Archive copy for keeper
and citation).

Two questions, ONE table. ``_SPECIALS`` powers both answers and they are deliberately
NOT one list:

- **copy rank** ("how good is this copy?") demotes all of it — Trash spellings *and*
  Junk/Spam/Archive/All Mail;
- **trash-ness** ("is this a Trash?") is only the trash spellings.

Collapsing them would re-break the false-match bugs the rank patterns encode: patterns
anchor to the FINAL path segment because both-side wrapping ('%Junk%', '%All%Mail')
matched real user folders ('Junkyard', 'Wallets/Old Mail') and demoted them, and
Junk/Spam take a '<name>' or '<name>%20…' segment because Exchange spells the folder
``Junk%20E-mail``, which a bare end-anchored '%/Junk' would rank as a preferred filed
folder and let beat a real Archive copy.

Pure by design — stdlib only, no native imports, no sibling-adapter imports — so
mail_index, mail_addressing, mail and dedupe can all use it without ordering concerns.
"""

from __future__ import annotations

from urllib.parse import unquote

# One row per special mailbox spelling: (decoded leaf, is_trash, prefix_ok).
# ``prefix_ok`` also matches '<leaf> …' (encoded: '<leaf>%20…') — Exchange's
# `Junk E-mail`. Spellings device-verified 2026-08-05 across four account types:
# IMAP `Trash`, iCloud `Deleted Messages`, Gmail `[Gmail]/Trash` (leaf: `Trash`) —
# plus `Bin`, the spelling the drifted vocabularies disagreed about.
_SPECIALS = (
    ("Trash", True, False),
    ("Deleted Messages", True, False),
    ("Bin", True, False),
    ("All Mail", False, False),
    ("Archive", False, False),
    ("Junk", False, True),
    ("Spam", False, True),
)

# Decoded, lowercased trash leaves — dedupe's is-this-a-trash membership test.
TRASH_LEAVES = frozenset(leaf.lower() for leaf, is_trash, _ in _SPECIALS if is_trash)


def _like_leaf(leaf: str) -> str:
    """A raw mailboxes.url is percent-ENCODED, so the space in a leaf is a literal
    '%20' — the '%' must be LIKE-escaped or it reads as a wildcard."""
    return "%/" + leaf.replace(" ", r"\%20")


# LIKE patterns (final-segment-anchored, ESCAPE '\\') for "is this a Trash?" in SQL —
# bound as params by mail_index.build_trash_query.
TRASH_SUFFIXES = tuple(_like_leaf(leaf) for leaf, is_trash, _ in _SPECIALS if is_trash)


def rank_case(col: str) -> str:
    """The copy-rank CASE expression over ``col`` (a mailboxes.url column): a live
    INBOX copy (0) beats a filed copy (1), which beats any special-mailbox copy (2).
    Fixed literals from ``_SPECIALS`` — never user input."""
    demoted = []
    for leaf, _is_trash, prefix_ok in _SPECIALS:
        demoted.append(f"{col} LIKE '{_like_leaf(leaf)}' ESCAPE '\\'")
        if prefix_ok:
            demoted.append(f"{col} LIKE '{_like_leaf(leaf)}\\%20%' ESCAPE '\\'")
    branches = "\n             OR ".join(demoted)
    return f"""CASE
           WHEN {col} LIKE '%/INBOX' THEN 0
           WHEN {branches} THEN 2
           ELSE 1 END"""


def parse(url: str) -> tuple[str, str, str] | None:
    """``(scheme, account uuid, DECODED path)`` — or None when ``url`` isn't a
    mailbox url (no ``://``). Empty uuid/path segments come back as '' — callers
    that must refuse them say so with their own error wording."""
    scheme, sep, rest = url.strip().partition("://")
    if not sep:
        return None
    uuid, _, raw_path = rest.partition("/")
    return scheme, uuid, unquote(raw_path)


def account(url: str) -> str | None:
    """The account uuid embedded in a mailbox url; None for a non-url."""
    parsed = parse(url)
    return (parsed[1] or None) if parsed else None


def path(url: str) -> str:
    """The DECODED mailbox path ('[Gmail]/Trash'); '' for a non-url."""
    parsed = parse(url)
    return parsed[2] if parsed else ""


def leaf(url: str) -> str:
    """The DECODED final path segment ('Trash') — a display name, never an address:
    §5 of the facts doc, a leaf read back from Mail does not round-trip."""
    return unquote(url.rsplit("/", 1)[-1])


def make(scheme: str, uuid: str, mailbox_path: str) -> str:
    """Synthesise the url for a mailbox the Envelope Index doesn't know yet
    (create_mailbox: ``make new mailbox`` returns ``missing value``, the mailbox class
    has no url property, and the index lags the sync — all three sources blind). Not
    byte-identical to the token Mail eventually stores (Mail encodes spaces); both
    DECODE to the same mailbox and nothing compares these tokens by equality."""
    return f"{scheme}://{uuid}/{mailbox_path}"


def is_trash(url: str) -> bool:
    """Is this mailbox a Trash? Compared on the DECODED final segment, so
    ``%5BGmail%5D/Trash`` and ``Deleted%20Messages`` both resolve."""
    return leaf(url).strip().lower() in TRASH_LEAVES
