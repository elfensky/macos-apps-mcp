# Mail Triage Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two read tools — `mail_needs_response()` and `mail_awaiting_reply(days=3)` — returning ranked `Pointer`s with a machine-readable `reason`, from header/property heuristics (no body scan).

**Architecture:** Pure fixture-tested classifiers over message *records*; AppleScript extracts the records (integration). awaiting-reply uses **real header threading** (Message-ID ↔ In-Reply-To/References), parsed with Python's stdlib `email`. All AppleScript below is **verified on-device**.

**Tech Stack:** Python 3.12+, FastMCP 2.0, osascript (Automation TCC), `email` + `re` (stdlib), pytest, uv, ruff.

## Global Constraints

- Tools in `server.py` are THIN dispatch. Reads return `Pointer`s (uniform read side). No message *body* content is read.
- **AppleScript gotchas (learned on-device — do not "clean up"):** build each record by INLINING field access into a `&` concatenation; a `set x to (read status of m)` statement mis-parses because `read`/`was` lead like commands — booleans coerce fine inside `&`. Addresses via `extract address from (sender of m)` and batched `address of every to recipient of m` (one Apple Event) joined with TID. Dates emitted as **seconds-ago** = `((current date) - (date received of m)) as integer`; Python converts. `email addresses` joined via `(email addresses of acc) as text` with TID (NOT element iteration — that raises `-1700`). Iterate `message i of inbox` for i=1..N (message 1 is newest — verified).
- Injection-safe: all inputs via argv; every script has `with timeout`.
- Reason vocabulary is FIXED: `flagged`, `unread-direct`, `unanswered-direct`, `awaiting-reply`. Additive only.
- Bounds: output `MAX_MAILS = 25`; inbox/sent scan caps `NEEDS_SCAN = SENT_SCAN = 100`; reply-header window cap `REFS_SCAN = 150`. Document these as the honest ceiling (#70 Envelope Index is the scalable upgrade).
- `reason` is an optional `Pointer` field (mirrors the existing optional `folder`); `_emit` includes it when set.
- Both tools `@_read_tool`, permission `"Automation"`, classified in `test_tool_annotations`; reads → audit-exempt, ride the untrusted-data notice.
- Style: ruff (88; E, F, I, UP, B, SIM). No mypy.
- Verify: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration (`-m integration`) manual only.
- Branch: `feat/68-mail-triage` (already created).

---

### Task 1: `Pointer.reason` + `_emit` + `_classify_needs_response`

**Files:**
- Modify: `macos_apps_mcp/contracts.py` (add `reason` to `Pointer`)
- Modify: `macos_apps_mcp/server.py` (`_emit` emits `reason`)
- Modify: `macos_apps_mcp/adapters/mail.py` (add `_classify_needs_response`)
- Test: `tests/test_mail_triage.py` (create), `tests/test_server.py` (reason round-trip)

**Interfaces:**
- Produces: `Pointer.reason: str | None = None`; `_emit` includes `reason`; `mail._classify_needs_response(records, my_addrs) -> list[Pointer]`.
- Record shape (a dict): `{"id": str, "subject": str, "sender": str, "to_addrs": list[str], "secs_ago": int, "was_replied_to": bool, "read": bool, "flagged": bool}`. Addresses are already lowercased bare addresses.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mail_triage.py`:

```python
"""Unit tests for mail triage — pure classifiers over fixtures (no TCC)."""

from __future__ import annotations

from macos_apps_mcp.adapters.mail import _classify_needs_response

ME = {"me@x.com"}


def _rec(**kw):
    base = {
        "id": "<m1@x>",
        "subject": "Hi",
        "sender": "bob@y.com",
        "to_addrs": ["me@x.com"],
        "secs_ago": 100,
        "was_replied_to": False,
        "read": False,
        "flagged": False,
    }
    base.update(kw)
    return base


def test_needs_response_drops_replied():
    out = _classify_needs_response([_rec(was_replied_to=True)], ME)
    assert out == []


def test_needs_response_drops_non_direct():
    # I'm not in to_addrs (cc-only / bulk) → dropped
    out = _classify_needs_response([_rec(to_addrs=["someone@else.com"])], ME)
    assert out == []


def test_needs_response_tiers_and_reasons():
    recs = [
        _rec(id="<f@x>", flagged=True, read=True),  # flagged wins even if read
        _rec(id="<u@x>", read=False),  # unread-direct
        _rec(id="<a@x>", read=True),  # unanswered-direct
    ]
    out = _classify_needs_response(recs, ME)
    assert [(p.id, p.reason) for p in out] == [
        ("<f@x>", "flagged"),
        ("<u@x>", "unread-direct"),
        ("<a@x>", "unanswered-direct"),
    ]


def test_needs_response_recency_tiebreak_within_tier():
    recs = [
        _rec(id="<old@x>", read=False, secs_ago=900),
        _rec(id="<new@x>", read=False, secs_ago=10),
    ]
    out = _classify_needs_response(recs, ME)
    assert [p.id for p in out] == ["<new@x>", "<old@x>"]  # most recent first


def test_needs_response_empty_my_addrs_degrades_to_flagged_only():
    recs = [_rec(id="<f@x>", flagged=True), _rec(id="<u@x>", read=False)]
    out = _classify_needs_response(recs, set())
    assert [p.id for p in out] == ["<f@x>"]  # flagged only, no flood


def test_needs_response_bounded():
    recs = [_rec(id=f"<m{i}@x>", read=False, secs_ago=i) for i in range(40)]
    assert len(_classify_needs_response(recs, ME)) == 25
```

Add to `tests/test_server.py`:

```python
def test_emit_includes_reason_when_set():
    from macos_apps_mcp.contracts import Pointer

    assert srv._emit(Pointer(id="i", summary="s", deeplink="d", reason="flagged")) == {
        "id": "i",
        "summary": "s",
        "deeplink": "d",
        "reason": "flagged",
    }
    assert "reason" not in srv._emit(Pointer(id="i", summary="s", deeplink="d"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_mail_triage.py tests/test_server.py::test_emit_includes_reason_when_set -v`
Expected: FAIL (`cannot import name '_classify_needs_response'` / reason absent).

- [ ] **Step 3: Implement**

`macos_apps_mcp/contracts.py` — add to the `Pointer` dataclass, after `folder`:

```python
    reason: str | None = None  # triage reads only: a stable machine-readable why-string
```

`macos_apps_mcp/server.py` — in `_emit`, before `return d`:

```python
    if p.reason is not None:
        d["reason"] = p.reason
```

`macos_apps_mcp/adapters/mail.py` — add `MAX_MAILS`-bounded classifier (near the other helpers):

```python
def _classify_needs_response(records: list[dict], my_addrs: set[str]) -> list[Pointer]:
    """Rank inbound messages that likely need the user's response. Drops already-replied
    messages; keeps those directly addressed to the user (my_addrs ∩ to_addrs). If
    my_addrs is empty (extraction failed) it degrades to FLAGGED-ONLY rather than flooding
    the inbox. Reasons (stable): flagged > unread-direct > unanswered-direct; recency
    (smallest secs_ago) breaks ties within a tier. Bounded to MAX_MAILS."""
    out: list[tuple[int, int, Pointer]] = []
    for r in records:
        if r["was_replied_to"]:
            continue
        direct = bool(my_addrs & set(r["to_addrs"]))
        if my_addrs and not direct:
            continue
        if not my_addrs and not r["flagged"]:
            continue  # can't confirm direct → flagged-only, no flood
        if r["flagged"]:
            tier, reason = 0, "flagged"
        elif not r["read"]:
            tier, reason = 1, "unread-direct"
        else:
            tier, reason = 2, "unanswered-direct"
        p = Pointer(
            id=r["id"],
            summary=clean_summary(_summary(r["subject"], r["sender"])),
            deeplink=_deeplink(r["id"]),
            reason=reason,
        )
        out.append((tier, r["secs_ago"], p))
    out.sort(key=lambda t: (t[0], t[1]))  # tier asc, then most-recent (secs_ago) first
    return [p for _, _, p in out[:MAX_MAILS]]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_mail_triage.py tests/test_server.py::test_emit_includes_reason_when_set -v`
Expected: PASS.

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/contracts.py macos_apps_mcp/server.py macos_apps_mcp/adapters/mail.py tests/test_mail_triage.py tests/test_server.py
git commit -m "feat(mail): Pointer.reason + needs-response classifier (#68)"
```

---

### Task 2: `_classify_awaiting_reply` + `_referenced_ids`

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py` (add `import email` + `_norm_mid`, `_referenced_ids`, `_classify_awaiting_reply`)
- Test: `tests/test_mail_triage.py` (extend)

**Interfaces:**
- Produces:
  - `mail._norm_mid(mid: str) -> str` — strip `<>`, lowercase.
  - `mail._referenced_ids(header_blobs: list[str]) -> set[str]` — normalized message-ids that inbox messages cite via In-Reply-To/References.
  - `mail._classify_awaiting_reply(sent, referenced_ids, days) -> list[Pointer]`.
- Sent record shape: `{"id": str, "subject": str, "recipient_addrs": list[str], "secs_ago": int}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mail_triage.py`:

```python
from macos_apps_mcp.adapters.mail import (
    _classify_awaiting_reply,
    _norm_mid,
    _referenced_ids,
)

DAY = 86400


def _sent(**kw):
    base = {
        "id": "<s1@x>",
        "subject": "Proposal",
        "recipient_addrs": ["bob@y.com"],
        "secs_ago": 5 * DAY,
    }
    base.update(kw)
    return base


def test_norm_mid():
    assert _norm_mid("<Abc@X>") == "abc@x"
    assert _norm_mid(" abc@x ") == "abc@x"


def test_referenced_ids_parses_folded_headers():
    blob = (
        "From: a@b.com\r\n"
        "In-Reply-To: <s1@x>\r\n"
        "References: <root@x>\r\n <s1@x>\r\n"  # folded continuation
        "Subject: Re: Proposal\r\n\r\n"
    )
    assert _referenced_ids([blob]) == {"s1@x", "root@x"}


def test_awaiting_reply_suppressed_when_id_referenced():
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"s1@x"}, days=3)
    assert out == []


def test_awaiting_reply_emitted_when_not_referenced():
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"other@x"}, days=3)
    assert [p.id for p in out] == ["<s1@x>"]
    assert out[0].reason == "awaiting-reply"


def test_awaiting_reply_same_subject_no_ref_does_not_suppress():
    # threading is by id, not subject: a same-subject reply that doesn't cite s1 → still awaiting
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"unrelated@x"}, days=3)
    assert [p.id for p in out] == ["<s1@x>"]


def test_awaiting_reply_days_threshold_excludes_recent():
    out = _classify_awaiting_reply([_sent(secs_ago=1 * DAY)], set(), days=3)
    assert out == []  # sent 1 day ago, threshold 3 days


def test_awaiting_reply_oldest_first():
    recs = [_sent(id="<a@x>", secs_ago=4 * DAY), _sent(id="<b@x>", secs_ago=9 * DAY)]
    out = _classify_awaiting_reply(recs, set(), days=3)
    assert [p.id for p in out] == ["<b@x>", "<a@x>"]  # most overdue first
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_mail_triage.py -k "awaiting or referenced or norm_mid" -v`
Expected: FAIL (imports missing).

- [ ] **Step 3: Implement**

`macos_apps_mcp/adapters/mail.py` — add `import email` and `import re` (check top; `re` may be absent) to the stdlib imports, and:

```python
def _norm_mid(mid: str) -> str:
    """Normalize a Message-ID for comparison: strip angle brackets + surrounding space,
    lowercase."""
    return mid.strip().lstrip("<").rstrip(">").strip().lower()


def _referenced_ids(header_blobs: list[str]) -> set[str]:
    """Message-ids cited by inbox messages via In-Reply-To / References. Each blob is one
    message's raw headers; stdlib email parses folded headers robustly."""
    ids: set[str] = set()
    for blob in header_blobs:
        msg = email.message_from_string(blob)
        refs = f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}"
        for tok in re.findall(r"<[^>]+>", refs):
            ids.add(_norm_mid(tok))
    return ids


def _classify_awaiting_reply(
    sent: list[dict], referenced_ids: set[str], days: int
) -> list[Pointer]:
    """Sent messages older than `days` whose Message-ID no inbox message references (real
    In-Reply-To/References threading — accurate, no fuzzy subject matching). Reason:
    stable 'awaiting-reply'. Sorted oldest-sent-first (most overdue). Bounded to MAX_MAILS.
    A group-thread send is cleared if ANY recipient's reply cites it (documented)."""
    cutoff = days * 86400
    out: list[tuple[int, Pointer]] = []
    for r in sent:
        if r["secs_ago"] < cutoff:
            continue
        if _norm_mid(r["id"]) in referenced_ids:
            continue
        to = ", ".join(r["recipient_addrs"]) or "(no recipients)"
        p = Pointer(
            id=r["id"],
            summary=clean_summary(f"{r['subject']} — to {to}"),
            deeplink=_deeplink(r["id"]),
            reason="awaiting-reply",
        )
        out.append((r["secs_ago"], p))
    out.sort(key=lambda t: t[0], reverse=True)  # most overdue (largest secs_ago) first
    return [p for _, p in out[:MAX_MAILS]]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_mail_triage.py -v`
Expected: PASS (all).

- [ ] **Step 5: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`

```bash
git add macos_apps_mcp/adapters/mail.py tests/test_mail_triage.py
git commit -m "feat(mail): awaiting-reply classifier via header threading (#68)"
```

---

### Task 3: AppleScript extractors + record parsers + adapter methods

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py` (4 verified AppleScript templates; `_parse_triage_records`, `_parse_sent_records`, `_parse_my_addrs`; `MailAdapter.get_needs_response`, `get_awaiting_reply`; scan-cap constants)
- Test: `tests/test_mail_triage.py` (parser tests), `tests/test_integration.py` (on-device)

**Interfaces:**
- Consumes: the classifiers (T1/T2), `run_osascript`.
- Produces: `MailAdapter.get_needs_response() -> list[Pointer]`, `MailAdapter.get_awaiting_reply(days: int = 3) -> list[Pointer]`; pure `_parse_triage_records(raw) -> list[dict]`, `_parse_sent_records(raw) -> list[dict]`, `_parse_my_addrs(raw) -> set[str]`.

- [ ] **Step 1: Write the failing parser tests**

Append to `tests/test_mail_triage.py`:

```python
from macos_apps_mcp.adapters.mail import (
    _parse_my_addrs,
    _parse_sent_records,
    _parse_triage_records,
)

US = "\x1f"
RS = "\x1e"


def test_parse_triage_records():
    raw = US.join(["<m1@x>", "Hi", "bob@y.com", "me@x.com,also@x.com", "120", "false", "true", "false"]) + RS
    recs = _parse_triage_records(raw)
    assert recs == [
        {
            "id": "<m1@x>",
            "subject": "Hi",
            "sender": "bob@y.com",
            "to_addrs": ["me@x.com", "also@x.com"],
            "secs_ago": 120,
            "was_replied_to": False,
            "read": True,
            "flagged": False,
        }
    ]


def test_parse_triage_skips_malformed():
    assert _parse_triage_records("") == []
    assert _parse_triage_records("only" + US + "two" + RS) == []  # too few fields


def test_parse_sent_records():
    raw = US.join(["<s1@x>", "Proposal", "bob@y.com,carol@z.com", "432000"]) + RS
    assert _parse_sent_records(raw) == [
        {
            "id": "<s1@x>",
            "subject": "Proposal",
            "recipient_addrs": ["bob@y.com", "carol@z.com"],
            "secs_ago": 432000,
        }
    ]


def test_parse_my_addrs_lowercases():
    assert _parse_my_addrs("Me@X.com" + US + "you@y.com" + US) == {"me@x.com", "you@y.com"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_mail_triage.py -k parse -v`
Expected: FAIL (imports missing).

- [ ] **Step 3: Implement the parsers + templates + methods**

`macos_apps_mcp/adapters/mail.py` — add scan caps near `MAX_MAILS`:

```python
NEEDS_SCAN = 100  # inbox messages scanned newest-first for needs-response
SENT_SCAN = 100  # recent sent messages scanned for awaiting-reply candidates
REFS_SCAN = 150  # inbox reply-headers scanned in the correlation window
```

Add the parsers:

```python
def _parse_triage_records(raw: str) -> list[dict]:
    """Parse _INBOX_TRIAGE: RS-separated records, US-separated fields (id, subject, sender,
    to_addrs (comma-joined), secs_ago, was_replied_to, read, flagged). Malformed/partial
    records are skipped; addresses lowercased."""
    out = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        f = record.split("\x1f")
        if len(f) < 8:
            continue
        out.append(
            {
                "id": f[0],
                "subject": f[1],
                "sender": f[2].strip().lower(),
                "to_addrs": [a.strip().lower() for a in f[3].split(",") if a.strip()],
                "secs_ago": int(f[4]) if f[4].strip().lstrip("-").isdigit() else 0,
                "was_replied_to": f[5].strip().lower() == "true",
                "read": f[6].strip().lower() == "true",
                "flagged": f[7].strip().lower() == "true",
            }
        )
    return out


def _parse_sent_records(raw: str) -> list[dict]:
    """Parse _SENT_TRIAGE: RS records, US fields (id, subject, recipients, secs_ago)."""
    out = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        f = record.split("\x1f")
        if len(f) < 4:
            continue
        out.append(
            {
                "id": f[0],
                "subject": f[1],
                "recipient_addrs": [a.strip().lower() for a in f[2].split(",") if a.strip()],
                "secs_ago": int(f[3]) if f[3].strip().lstrip("-").isdigit() else 0,
            }
        )
    return out


def _parse_my_addrs(raw: str) -> set[str]:
    return {a.strip().lower() for a in raw.split("\x1f") if a.strip()}
```

Add the four VERIFIED templates (copy exactly — the inlining and `get`-free forms are load-bearing):

```python
# _INBOX_TRIAGE: newest-first inbox records, US/RS framed. Fields INLINED into the concat
# (a `set x to (read status of m)` statement mis-parses — `read`/`was` lead like commands;
# booleans coerce inside `&`). Addresses bare (extract address from / address of every to
# recipient, TID-joined). Date as seconds-ago. maxN via argv. Verified on-device.
_INBOX_TRIAGE = """on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set n to (count of messages of inbox)
    if n > maxN then set n to maxN
    repeat with i from 1 to n
      set m to message i of inbox
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set AppleScript's text item delimiters to ","
        set toJoined to ((address of every to recipient of m) as text)
        set AppleScript's text item delimiters to ""
        set out to out & mid & us & (subject of m) & us & (extract address from (sender of m)) & us & toJoined & us & (((current date) - (date received of m)) as integer) & us & (was replied to of m) & us & (read status of m) & us & (flagged status of m) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""

# _SENT_TRIAGE: recent sent records from the unified `sent mailbox` (All Sent), newest-first.
_SENT_TRIAGE = """on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  with timeout of 120 seconds
  tell application "Mail"
    set sm to sent mailbox
    set n to (count of messages of sm)
    if n > maxN then set n to maxN
    repeat with i from 1 to n
      set m to message i of sm
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set AppleScript's text item delimiters to ","
        set toJoined to ((address of every to recipient of m) as text)
        set AppleScript's text item delimiters to ""
        set out to out & mid & us & (subject of m) & us & toJoined & us & (((current date) - (date sent of m)) as integer) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""

# _MY_ADDRESSES: the user's own addresses, US-framed (list-join with TID — element
# iteration raises -1700). Verified on-device.
_MY_ADDRESSES = """on run argv
  set us to character id 31
  set AppleScript's text item delimiters to us
  set out to ""
  with timeout of 60 seconds
  tell application "Mail"
    repeat with acc in accounts
      set out to out & ((email addresses of acc) as text) & us
    end repeat
  end tell
  end timeout
  set AppleScript's text item delimiters to ""
  return out
end run"""

# _INBOX_REFS: for inbox messages received within `cutoffSecs` ago (the correlation window),
# emit the RAW HEADERS (RS-framed) of only those that ARE replies (carry In-Reply-To /
# References) — Python parses referenced ids (stdlib email handles folding). Capped at maxN.
_INBOX_REFS = """on run argv
  set cutoffSecs to (item 1 of argv) as integer
  set maxN to (item 2 of argv) as integer
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    set cutoff to (current date) - cutoffSecs
    repeat with m in (messages of inbox whose date received > cutoff)
      set h to all headers of m
      if (h contains "In-Reply-To:") or (h contains "References:") then
        set c to c + 1
        if c > maxN then exit repeat
        set out to out & h & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
```

Add the methods to `MailAdapter`:

```python
    def get_needs_response(self) -> list[Pointer]:
        """Inbox messages that likely need the user's response, ranked with a reason
        (flagged / unread-direct / unanswered-direct). Heuristic over headers/properties —
        no body scan; direct-addressed + not-yet-replied. Bounded."""
        records = _parse_triage_records(run_osascript(_INBOX_TRIAGE, str(NEEDS_SCAN)))
        my = _parse_my_addrs(run_osascript(_MY_ADDRESSES))
        return _classify_needs_response(records, my)

    def get_awaiting_reply(self, days: int = 3) -> list[Pointer]:
        """Sent messages older than `days` with no reply, ranked oldest-first (reason
        'awaiting-reply'). Real In-Reply-To/References threading. Bounded."""
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        sent = _parse_sent_records(run_osascript(_SENT_TRIAGE, str(SENT_SCAN)))
        candidates = [r for r in sent if r["secs_ago"] >= days * 86400]
        if not candidates:
            return []
        window = max(r["secs_ago"] for r in candidates)  # scan inbox back to oldest send
        blobs = [
            b
            for b in run_osascript(_INBOX_REFS, str(window), str(REFS_SCAN)).split("\x1e")
            if b.strip()
        ]
        return _classify_awaiting_reply(sent, _referenced_ids(blobs), days)
```

- [ ] **Step 4: Run to verify parser tests pass**

Run: `uv run pytest tests/test_mail_triage.py -v`
Expected: PASS (all).

- [ ] **Step 5: Add integration tests (manual, on-device)**

In `tests/test_integration.py` (match the file's marker style; Mail uses Automation, no `request_access`):

```python
@pytest.mark.integration
def test_mail_needs_response_shape():
    from macos_apps_mcp.adapters.mail import MailAdapter

    ptrs = MailAdapter().get_needs_response()
    assert isinstance(ptrs, list) and len(ptrs) <= 25
    for p in ptrs:
        assert p.id and p.reason in {"flagged", "unread-direct", "unanswered-direct"}
        assert p.deeplink.startswith("message://")


@pytest.mark.integration
def test_mail_awaiting_reply_shape():
    from macos_apps_mcp.adapters.mail import MailAdapter

    ptrs = MailAdapter().get_awaiting_reply(days=3)
    assert isinstance(ptrs, list) and len(ptrs) <= 25
    for p in ptrs:
        assert p.id and p.reason == "awaiting-reply" and p.deeplink.startswith("message://")


@pytest.mark.integration
def test_mail_awaiting_reply_rejects_bad_days():
    import pytest as _pytest

    from macos_apps_mcp.adapters.mail import MailAdapter

    with _pytest.raises(ValueError):
        MailAdapter().get_awaiting_reply(days=0)
```

- [ ] **Step 6: Full verify + commit**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
(Integration deselected by default.)

```bash
git add macos_apps_mcp/adapters/mail.py tests/test_mail_triage.py tests/test_integration.py
git commit -m "feat(mail): triage AppleScript extractors + adapter methods (#68)"
```

---

### Task 4: Server tools + annotation + dispatch tests

**Files:**
- Modify: `macos_apps_mcp/server.py` (two tools)
- Modify: `tests/test_server.py` (dispatch tests), `tests/test_tool_annotations.py` (classify both)

**Interfaces:**
- Consumes: `MailAdapter.get_needs_response` / `get_awaiting_reply` (T3).
- Produces: `mail_needs_response`, `mail_awaiting_reply` MCP read tools.

- [ ] **Step 1: Write the failing dispatch + annotation tests**

Add to `tests/test_server.py` (extend the `_FakeSource` used for mail with the two methods, or add a small fake):

```python
def test_mail_needs_response_dispatches(monkeypatch):
    from macos_apps_mcp.contracts import Pointer

    class _F:
        def get_needs_response(self):
            return [Pointer(id="<m@x>", summary="s", deeplink="message://m", reason="flagged")]

    monkeypatch.setattr(srv, "_mail", _F())
    out = srv.mail_needs_response()
    assert out == [{"id": "<m@x>", "summary": "s", "deeplink": "message://m", "reason": "flagged"}]


def test_mail_awaiting_reply_dispatches(monkeypatch):
    from macos_apps_mcp.contracts import Pointer

    seen = {}

    class _F:
        def get_awaiting_reply(self, days=3):
            seen["days"] = days
            return [Pointer(id="<s@x>", summary="s", deeplink="message://s", reason="awaiting-reply")]

    monkeypatch.setattr(srv, "_mail", _F())
    out = srv.mail_awaiting_reply(7)
    assert seen["days"] == 7 and out[0]["reason"] == "awaiting-reply"
```

In `tests/test_tool_annotations.py`: add `"mail_needs_response": "Automation"` and `"mail_awaiting_reply": "Automation"` to `_PERMISSION` (both are read tools — not in the write sets).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_server.py -k "mail_needs or mail_awaiting" tests/test_tool_annotations.py -v`
Expected: FAIL (tools + permission entries missing).

- [ ] **Step 3: Add the tools**

`macos_apps_mcp/server.py` — near the other mail read tools:

```python
@_read_tool
def mail_needs_response() -> list[dict]:
    """Inbox messages that likely need your response, ranked with a machine-readable
    `reason` (flagged / unread-direct / unanswered-direct). Heuristic over headers +
    message properties — no body is read; keeps direct-addressed, not-yet-replied mail.
    Read-only; needs Automation access for Mail. Bounded to 25."""
    return [_emit(p) for p in _mail.get_needs_response()]


@_read_tool
def mail_awaiting_reply(days: int = 3) -> list[dict]:
    """Messages YOU sent more than `days` ago (1–365, default 3) with no reply, ranked
    oldest-first, reason `awaiting-reply`. Uses real In-Reply-To/References threading. A
    group send is cleared once any recipient replies. Read-only; needs Automation access
    for Mail. Bounded to 25."""
    return [_emit(p) for p in _mail.get_awaiting_reply(days)]
```

- [ ] **Step 4: Run the dispatch + annotation tests**

Run: `uv run pytest tests/test_server.py -k "mail_needs or mail_awaiting" tests/test_tool_annotations.py -v`
Expected: PASS.

- [ ] **Step 5: Full verification + commit**

Run:
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Expected: all pass; integration deselected.

```bash
git add macos_apps_mcp/server.py tests/test_server.py tests/test_tool_annotations.py
git commit -m "feat(mail): mail_needs_response + mail_awaiting_reply tools (#68)"
```

---

## Post-plan

- [ ] Run `uv run pytest -m integration -k mail` on-device to validate the extractors against the real mailbox before merge.
- [ ] Open a PR from `feat/68-mail-triage` → `develop`, closing #68 and completing the 0.7.0 Differentiators milestone. Note the honest bounds (scan caps; group-thread clearing on any reply; #70 Envelope Index as the scalable upgrade) and that the AppleScript was on-device-verified during design.
