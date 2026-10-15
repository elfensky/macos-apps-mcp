"""Contacts adapter — Contacts.app via AppleScript/osascript (Automation TCC).

Reads return Pointers; writes take ``ContactData``. Uses the osascript escape hatch
(``runtime.run_osascript``), NOT the Contacts framework: a non-bundled server can't get
``CNContactStore`` TCC (no usage-description bundle), but Automation TCC — scripting
Contacts.app — works, attributed to the responsible host app. See issue #15.

User input is passed as ``osascript`` argv (``on run argv``), not interpolated into
the script, so a name or id can't break out of the AppleScript.
"""

from __future__ import annotations

from .. import runtime
from ..contracts import ContactData, Pointer
from ..errors import VerificationFailed, verify_persisted
from ..text import US, Field, clean_summary, norm_text, parse_framed

MAX_CONTACTS = 50  # cap a broad name match

# Payload framing uses the canonical US/RS wire contract from text.py (#68): fields
# joined with US, people with RS — control chars instead of tab/newline, so a tab or
# newline *inside* a field can't split or spoof a row. The AppleScript emits them via
# `character id 31`/`character id 30`; split_framed is the Python-side counterpart.
# ponytail: US/RS are effectively absent from your own Contacts (trusted input), so this
# is treated as an invariant, not sanitized. A field carrying a literal 0x1f/0x1e (e.g.
# an adversarial vCard import) would still mis-split — adopt text.STRIP_FRAMING (as
# mail.py does) if seen in the wild.

# Each matching person -> "id|name|org|phone|email" (US-delimited, RS-terminated). Unset
# fields (`missing value` / no phones / no emails) normalize to "". Phone/email are the
# first of each — a citable handle to *reach* the person, not the full card.
# #334: on the Intel iMac every `whose` reference re-runs the scan. A broad query ("an",
# 52 matches of 192 people) scanned in 2 s, but the old loop touched `p` five times per
# person, so it ran past 600 s. Now each property is read with ONE Apple event over the
# whole match list (5 scans, 9 s measured on the same query). The five lists pair by
# index, so a length mismatch (a contact changed mid-read) raises instead of mixing two
# people's fields. maxN caps the rows built, passed via argv, not interpolated.
_SEARCH = """on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set uSep to character id 31
  set rSep to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Contacts"
    set idList to id of (people whose name contains q)
    set nameList to name of (people whose name contains q)
    set orgList to organization of (people whose name contains q)
    set phoneLists to value of phones of (people whose name contains q)
    set emailLists to value of emails of (people whose name contains q)
  end tell
  end timeout
  set howMany to count of idList
  if (count of nameList) is not howMany or (count of orgList) is not howMany then
    error "Contacts changed during the read; retry the search"
  end if
  if (count of phoneLists) is not howMany or (count of emailLists) is not howMany then
    error "Contacts changed during the read; retry the search"
  end if
  if howMany > maxN then set howMany to maxN
  repeat with i from 1 to howMany
    set theOrg to item i of orgList
    if theOrg is missing value then set theOrg to ""
    set phones_i to item i of phoneLists
    set emails_i to item i of emailLists
    set thePhone to ""
    if (count of phones_i) > 0 then set thePhone to item 1 of phones_i
    set theEmail to ""
    if (count of emails_i) > 0 then set theEmail to item 1 of emails_i
    set out to out & (item i of idList) & uSep & (item i of nameList) & uSep & theOrg
    set out to out & uSep & thePhone & uSep & theEmail & rSep
  end repeat
  return out
end run"""

_CREATE = """on run argv
  set fn to item 1 of argv
  set ln to item 2 of argv
  set org to item 3 of argv
  with timeout of 120 seconds
  tell application "Contacts"
    set p to make new person with properties {first name:fn}
    if ln is not "" then set last name of p to ln
    if org is not "" then set organization of p to org
    save
    return id of p
  end tell
  end timeout
end run"""

# Re-read a person by the id we're about to return (#49) — proves the create persisted
# and didn't silently drop a field. `person id` is the direct O(1) specifier (the form
# notes.py already uses); a whose-filter would scan the whole address book. Emits
# "firstname|lastname|org" (US-delimited); an empty return means the id resolves to
# nothing (fabricated / not saved). id via argv.
_VERIFY = """on run argv
  set pid to item 1 of argv
  set uSep to character id 31
  with timeout of 120 seconds
  tell application "Contacts"
    try
      set p to person id pid
    on error
      return ""
    end try
    set fn to first name of p
    if fn is missing value then set fn to ""
    set ln to last name of p
    if ln is missing value then set ln to ""
    set org to organization of p
    if org is missing value then set org to ""
    return fn & uSep & ln & uSep & org
  end tell
  end timeout
end run"""


def _verify_contact(raw: str, ident: str, data: ContactData) -> None:
    """Re-query verify (#49): fail loudly if the created contact can't be re-read or a
    requested field didn't persist. `raw` is the ``_VERIFY`` payload for ``ident``."""
    # run_osascript already strips osascript's single terminating newline, so `raw` is
    # the payload as-is — never str.strip() it: the \x1f/\x1e separators are Unicode
    # whitespace, so strip() would eat a leading empty given_name's delimiter and shift
    # every field left. _VERIFY returns "" (empty) for a not-found id.
    if not raw:
        raise VerificationFailed(
            f"contact {ident!r} could not be re-read after save — the write did not "
            "persist (a fabricated id or an unsaved record). Do not trust the id."
        )
    parts = raw.split(US)
    fn = parts[0] if parts else ""
    ln = parts[1] if len(parts) > 1 else ""
    org = parts[2] if len(parts) > 2 else ""
    expected = {
        # norm_text folds "" ↔ None on BOTH sides (an org-only contact has an empty
        # given_name) and NFC/LF-normalizes, so a correct save can't false-fail (#49).
        "given_name": norm_text(data.given_name),
        "family_name": norm_text(data.family_name),
        "organization": norm_text(data.organization),
    }
    actual = {
        "given_name": norm_text(fn),
        "family_name": norm_text(ln),
        "organization": norm_text(org),
    }
    verify_persisted("contact", expected, actual)


def _summary(name: str, org: str, phone: str = "", email: str = "") -> str:
    name, org = name.strip(), org.strip()
    head = f"{name} — {org}" if (name and org) else (name or org)
    contact = " · ".join(x for x in (phone.strip(), email.strip()) if x)
    if head and contact:
        return f"{head} · {contact}"
    return head or contact or "(unnamed contact)"


def _deeplink(ident: str) -> str:
    # addressbook://<id> opens Contacts to the card (best-effort; verify on-device).
    return f"addressbook://{ident}"


def _parse(raw: str) -> list[Pointer]:
    recs = parse_framed(
        raw,
        [Field("id"), Field("name"), Field("org"), Field("phone"), Field("email")],
        min_fields=1,
    )
    return [
        Pointer(
            id=r["id"],
            summary=clean_summary(
                _summary(r["name"], r["org"], r["phone"], r["email"])
            ),
            deeplink=_deeplink(r["id"]),
        )
        for r in recs
    ]


class ContactsAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a name (substring) to match, e.g. 'jane' or 'Jane Doe'."""
        name = query.strip()
        if not name:
            raise ValueError("contacts read needs a name to match (got an empty query)")
        # AppleScript caps at MAX_CONTACTS; the slice is a cheap backstop on its output.
        raw = runtime.run_osascript(_SEARCH, name, str(MAX_CONTACTS))
        return _parse(raw)[:MAX_CONTACTS]

    def create_contact(self, data: ContactData) -> Pointer:
        ident = runtime.run_osascript(
            _CREATE, data.given_name, data.family_name or "", data.organization or ""
        ).strip()
        # Re-read by the id we're about to return — never trust the create's echo (#49).
        _verify_contact(runtime.run_osascript(_VERIFY, ident), ident, data)
        full = f"{data.given_name} {data.family_name or ''}"
        return Pointer(
            id=ident,
            summary=clean_summary(_summary(full, data.organization or "")),
            deeplink=_deeplink(ident),
        )
