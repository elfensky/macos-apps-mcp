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
Exchange Junk spellings are explicit: a prefix such as 'Junk …' would also demote
a user folder named 'Junk research'. Names remain heuristics, not server role proof.

Pure by design — stdlib only, no native imports, no sibling-adapter imports — so
mail_index, mail_addressing, mail and dedupe can all use it without ordering concerns.
"""

from __future__ import annotations

import unicodedata
from urllib.parse import quote, unquote

# One row per exact special mailbox spelling: (decoded leaf, is_trash).
# English names have recorded device evidence; nl/de/fr/ru names come from Google,
# Microsoft and Apple resources. See .planning/phases/05.6-*/05.6-02-SUMMARY.md.
# Match only whole leaves: neither translated stems nor arbitrary word suffixes.
# Gmail roots ([Gmail] and [Google Mail]) do not change the final leaf.
_SPECIALS = (
    ("Trash", True),
    ("Deleted Messages", True),
    ("Deleted Items", True),
    ("Bin", True),
    ("Prullenbak", True),
    ("Prullenmand", True),
    ("Verwijderde items", True),
    ("Papierkorb", True),
    ("Gelöschte Elemente", True),
    ("Corbeille", True),
    ("Éléments supprimés", True),
    ("Корзина", True),
    ("Удаленные", True),
    ("All Mail", False),
    ("Alle e-mail", False),
    ("Alle Nachrichten", False),
    ("Tous les messages", False),
    ("Вся почта", False),
    ("Archive", False),
    ("Archief", False),
    ("Archiv", False),
    ("Архив", False),
    ("Junk", False),
    ("Spam", False),
    ("Junk E-mail", False),
    ("Junk Email", False),
    ("Junk-E-Mail", False),
    ("Ongewenste e-mail", False),
    ("Ongewenste Email", False),
    ("Courrier indésirable", False),
    ("Indésirables", False),
    ("Спам", False),
    ("Нежелательная почта", False),
)

# Normalize only classification keys, never mailbox addressing strings.
TRASH_LEAVES = frozenset(
    unicodedata.normalize("NFC", leaf).casefold()
    for leaf, is_trash in _SPECIALS
    if is_trash
)


def _like_leaf(leaf: str) -> str:
    """Mail stores uppercase percent-encoded UTF-8, leaving &() literal (D-13).
    Escape SQL wildcards AFTER encoding, including every literal percent sign."""
    encoded = quote(leaf, safe="&()")
    return "%/" + encoded.replace("%", r"\%").replace("_", r"\_")


def _leaf_patterns(names: tuple[str, ...]) -> tuple[str, ...]:
    """Both recorded Unicode storage forms, without duplicate ASCII patterns."""
    return tuple(
        dict.fromkeys(
            _like_leaf(unicodedata.normalize(form, name))
            for name in names
            for form in ("NFC", "NFD")
        )
    )


# LIKE patterns (final-segment-anchored, ESCAPE '\\') for "is this a Trash?" in SQL —
# bound as params by mail_index.build_trash_query.
TRASH_SUFFIXES = _leaf_patterns(tuple(leaf for leaf, trash in _SPECIALS if trash))

# Sent-role leaves (#192) — device-verified 2026-08-20 across this Mac's account
# types: IMAP/Yahoo `Sent`, iCloud `Sent Messages`, Gmail `[Gmail]/Sent Mail`
# (leaf: `Sent Mail`). `Sent Items` is Exchange's standard spelling, included so
# an Exchange account doesn't silently vanish from the awaiting-reply scan.
# Final-segment-anchored like TRASH_SUFFIXES, and for the same reason: a user
# folder named `Sentimental` must not read as a Sent mailbox.
SENT_LEAVES = (
    "Sent",
    "Sent Messages",
    "Sent Mail",
    "Sent Items",
    "Verzonden",
    "Verzonden berichten",
    "Verzonden items",
    "Gesendet",
    "Gesendete Elemente",
    "Messages envoyés",
    "Éléments envoyés",
    "Отправленные",
)
SENT_SUFFIXES = _leaf_patterns(SENT_LEAVES)


def rank_case(col: str) -> str:
    """The copy-rank CASE expression over ``col`` (a mailboxes.url column): a live
    INBOX copy (0) beats a filed copy (1), which beats any special-mailbox copy (2).
    Fixed literals from ``_SPECIALS`` — never user input."""
    demoted = [
        f"{col} LIKE '{pattern}' ESCAPE '\\'"
        for pattern in _leaf_patterns(tuple(leaf for leaf, _ in _SPECIALS))
    ]
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
    return unicodedata.normalize("NFC", leaf(url)).casefold() in TRASH_LEAVES
