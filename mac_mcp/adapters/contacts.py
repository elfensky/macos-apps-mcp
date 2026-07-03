"""Contacts adapter — Contacts.app via AppleScript/osascript (Automation TCC).

Reads return Pointers; writes take ``ContactData``. Uses the osascript escape hatch
(``runtime.run_osascript``), NOT the Contacts framework: a non-bundled server can't get
``CNContactStore`` TCC (no usage-description bundle), but Automation TCC — scripting
Contacts.app — works, attributed to the responsible host app. See issue #15.

User input is passed as ``osascript`` argv (``on run argv``), not interpolated into
the script, so a name or id can't break out of the AppleScript.
"""

from __future__ import annotations

from ..contracts import ContactData, Pointer
from ..runtime import VerificationFailed, run_osascript, verify_persisted

MAX_CONTACTS = 50  # cap a broad name match

# Field/record delimiters for the osascript payload: control chars instead of
# tab/newline, so a tab or newline *inside* a field can't split or spoof a row. _parse
# splits on these; the AppleScript emits them via `character id`.
# ponytail: US/RS are effectively absent from your own Contacts (trusted input), so this
# is treated as an invariant, not sanitized. A field carrying a literal 0x1f/0x1e (e.g.
# an adversarial vCard import) would still mis-split — strip them if seen in the wild.
_FIELD = "\x1f"  # ASCII Unit Separator — between fields
_RECORD = "\x1e"  # ASCII Record Separator — between people

# Each matching person -> "id|name|org|phone|email" (US-delimited, RS-terminated). Unset
# fields (`missing value` / no phones / no emails) normalize to "". Phone/email are the
# first of each — a citable handle to *reach* the person, not the full card.
# maxN bounds the work IN AppleScript: stop after maxN matches so a broad query ("a")
# doesn't fetch phone/email for thousands of people just to have Python drop all but the
# first MAX_CONTACTS. (The `whose name contains` scan itself is one cheap Apple Events
# call; the per-person property fetches below are the expensive part this `exit repeat`
# caps.) The cap is passed via argv, not interpolated.
_SEARCH = """on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set uSep to character id 31
  set rSep to character id 30
  set out to ""
  set n to 0
  tell application "Contacts"
    repeat with p in (people whose name contains q)
      set theOrg to organization of p
      if theOrg is missing value then set theOrg to ""
      set thePhone to ""
      if (count of phones of p) > 0 then set thePhone to value of item 1 of phones of p
      set theEmail to ""
      if (count of emails of p) > 0 then set theEmail to value of item 1 of emails of p
      set out to out & (id of p) & uSep & (name of p) & uSep & theOrg
      set out to out & uSep & thePhone & uSep & theEmail & rSep
      set n to n + 1
      if n >= maxN then exit repeat
    end repeat
  end tell
  return out
end run"""

_CREATE = """on run argv
  set fn to item 1 of argv
  set ln to item 2 of argv
  set org to item 3 of argv
  tell application "Contacts"
    set p to make new person with properties {first name:fn}
    if ln is not "" then set last name of p to ln
    if org is not "" then set organization of p to org
    save
    return id of p
  end tell
end run"""

# Re-read a person by the id we're about to return (#49) — proves the create persisted
# and didn't silently drop a field. Emits "firstname|lastname|org" (US-delimited); an
# empty return means the id resolves to nothing (fabricated / not saved). id via argv.
_VERIFY = """on run argv
  set pid to item 1 of argv
  set uSep to character id 31
  tell application "Contacts"
    set matches to (people whose id is pid)
    if (count of matches) is 0 then return ""
    set p to item 1 of matches
    set fn to first name of p
    if fn is missing value then set fn to ""
    set ln to last name of p
    if ln is missing value then set ln to ""
    set org to organization of p
    if org is missing value then set org to ""
    return fn & uSep & ln & uSep & org
  end tell
end run"""


def _verify_contact(raw: str, ident: str, data: ContactData) -> None:
    """Re-query verify (#49): fail loudly if the created contact can't be re-read or a
    requested field didn't persist. `raw` is the ``_VERIFY`` payload for ``ident``."""
    # rstrip ONLY the newline — NOT str.strip(): the \x1f/\x1e separators are Unicode
    # whitespace, so strip() would eat a leading empty given_name's delimiter and shift
    # every field left. _VERIFY returns "" (empty) for a not-found id.
    raw = raw.rstrip("\n")
    if not raw:
        raise VerificationFailed(
            f"contact {ident!r} could not be re-read after save — the write did not "
            "persist (a fabricated id or an unsaved record). Do not trust the id."
        )
    parts = raw.split(_FIELD)
    fn = parts[0] if parts else ""
    ln = parts[1] if len(parts) > 1 else ""
    org = parts[2] if len(parts) > 2 else ""
    expected = {
        # normalize "" ↔ None on BOTH sides (as with family_name/organization) so an
        # empty given_name — an org-only contact — doesn't false-fail a correct save.
        "given_name": data.given_name or None,
        "family_name": data.family_name or None,  # "" and None are both "no last name"
        "organization": data.organization or None,
    }
    actual = {
        "given_name": fn or None,
        "family_name": ln or None,
        "organization": org or None,
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
    out = []
    for rec in raw.split(_RECORD):
        if not rec.strip():
            continue
        parts = rec.split(_FIELD)
        ident = parts[0]
        name = parts[1] if len(parts) > 1 else ""
        org = parts[2] if len(parts) > 2 else ""
        phone = parts[3] if len(parts) > 3 else ""
        email = parts[4] if len(parts) > 4 else ""
        out.append(
            Pointer(
                id=ident,
                summary=_summary(name, org, phone, email),
                deeplink=_deeplink(ident),
            )
        )
    return out


class ContactsAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a name (substring) to match, e.g. 'jane' or 'Jane Doe'."""
        name = query.strip()
        if not name:
            raise ValueError("contacts read needs a name to match (got an empty query)")
        # AppleScript caps at MAX_CONTACTS; the slice is a cheap backstop on its output.
        return _parse(run_osascript(_SEARCH, name, str(MAX_CONTACTS)))[:MAX_CONTACTS]

    def create_contact(self, data: ContactData) -> Pointer:
        ident = run_osascript(
            _CREATE, data.given_name, data.family_name or "", data.organization or ""
        ).strip()
        # Re-read by the id we're about to return — never trust the create's echo (#49).
        _verify_contact(run_osascript(_VERIFY, ident), ident, data)
        full = f"{data.given_name} {data.family_name or ''}"
        return Pointer(
            id=ident,
            summary=_summary(full, data.organization or ""),
            deeplink=_deeplink(ident),
        )
