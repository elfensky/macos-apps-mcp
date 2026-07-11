"""Mail adapter — Mail.app via osascript (Automation TCC). Read-only v1: inbox search.

Mail has a rich AppleScript dictionary. ``Pointer.id`` is the RFC822 ``message id``
(stable across relaunch — the citation contract), NOT the AppleScript object ``id`` (a
session-local integer that rots across relaunch, so never a durable citation). Actions
resolve a message BY that RFC id. ``deeplink`` is a ``message://`` URL built from the
same RFC id. Pointers, not bodies. Search matches subject OR sender over the inbox;
Mail's AppleScript is slow on large mailboxes, so results are capped and the osascript
timeout bounds a pathological search. User input goes via argv (no script injection).
"""

from __future__ import annotations

from urllib.parse import quote

from ..contracts import Pointer
from ..runtime import clean_summary, run_osascript

MAX_MAILS = 25

# Localized system-mailbox name tables (#61): Mail names these per-locale, so a
# a US-hardcoded "Inbox" gives "mailbox not found" on a non-English Mac. Static data
# used by any mailbox-scoped operation (#45 / the reply-draft issues) to try each
# candidate name. Canonical → localized names; en/nl/ru at least (the acceptance floor).
# ponytail: extend per locale as needed — the exact Mail.app strings want on-device
# confirmation, but a miss only means that mailbox isn't found there, never a crash.
_SYSTEM_MAILBOXES = {
    "inbox": ("Inbox", "Postvak IN", "Входящие"),
    "sent": ("Sent", "Verzonden", "Отправленные"),
    "drafts": ("Drafts", "Concepten", "Черновики"),
    "trash": ("Trash", "Prullenmand", "Корзина"),
    "junk": ("Junk", "Ongewenste reclame", "Спам"),
}


def system_mailbox_names(canonical: str) -> tuple[str, ...]:
    """Localized name candidates for a canonical system mailbox (inbox/sent/drafts/
    trash/junk) — a mailbox-scoped op tries each until Mail resolves one. Raises on an
    unknown canonical name so a typo fails loudly rather than silently matching none."""
    key = canonical.strip().lower()
    if key not in _SYSTEM_MAILBOXES:
        raise ValueError(
            f"unknown system mailbox {canonical!r}; expected one of "
            f"{sorted(_SYSTEM_MAILBOXES)}"
        )
    return _SYSTEM_MAILBOXES[key]


# Bounded host-side (#52): stop emitting after maxN matches instead of streaming the
# whole match set back and slicing in Python. The `whose` filter still scans the inbox
# (AppleScript has no LIMIT), but the *output* is capped at the source, so a common
# subject can't return thousands of records and blow the buffer (FradSer #66/#69).
# Matches subject OR sender (#61). with timeout (#56): bound the Apple Events so an
# orphaned osascript can't pin Mail.
_SEARCH = """on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    repeat with m in (messages of inbox whose (subject contains q or sender contains q))
      set mid to message id of m
      -- RFC 5322 message-id is only SHOULD: a header-less message yields `missing
      -- value`. Skip it — it has no stable citation (never emit a garbage id). #61
      if mid is not missing value and mid is not "" then
        set c to c + 1
        if c > maxN then exit repeat
        set out to out & mid & tab & (subject of m) & tab & (sender of m) & linefeed
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""


def _summary(subject: str, sender: str) -> str:
    subject, sender = subject.strip(), sender.strip()
    if subject and sender:
        return f"{subject} — {sender}"
    return subject or sender or "(no subject)"


def _deeplink(message_id: str) -> str:
    # message://%3C<id>%3E opens the message in Mail. The angle brackets are percent-
    # encoded (%3C/%3E) and the id itself is percent-encoded with safe='@' (an RFC822
    # message-id is local@domain, so '@' stays literal; spaces/other chars escaped) —
    # the patrickfreyer recipe (#61). Best-effort; verified on-device (integration).
    mid = message_id.strip().lstrip("<").rstrip(">")
    return f"message://%3C{quote(mid, safe='@')}%3E"


def _parse(raw: str) -> list[Pointer]:
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        mid = parts[0]
        # a message with no Message-ID header has no stable citation — skip it rather
        # than emit a non-resolvable id ("missing value" is AppleScript's coercion of an
        # unset property; "" is the alternative some Mail versions return). #61 review.
        if mid.strip() in ("", "missing value"):
            continue
        subject = parts[1] if len(parts) > 1 else ""
        sender = parts[2] if len(parts) > 2 else ""
        out.append(
            Pointer(
                id=mid,
                summary=clean_summary(_summary(subject, sender)),
                deeplink=_deeplink(mid),
            )
        )
    return out


class MailAdapter:
    def get_pointers(self, query: str) -> list[Pointer]:
        """query: a substring to match against the inbox subject OR sender (#61)."""
        q = query.strip()
        if not q:
            raise ValueError("mail read needs a search substring (got an empty query)")
        # maxN is enforced host-side; the slice is a cheap backstop on the result.
        return _parse(run_osascript(_SEARCH, q, str(MAX_MAILS)))[:MAX_MAILS]
