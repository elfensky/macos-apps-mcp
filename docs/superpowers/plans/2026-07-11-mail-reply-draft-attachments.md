# Mail reply / draft / attachment surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give mac-mcp's mail adapter a small, safe reply/draft/attachment surface (#42–#46): list attachments by mailbox+query, make draft creation atomic with an honest locator, and add a threaded `reply` via Mail's native `reply` verb — never sending.

**Architecture:** All logic in `mac_mcp/adapters/mail.py` (osascript templates + thin Python), thin-dispatched from `mac_mcp/server.py`. Reuses the shipped primitives (`system_mailbox_names`, `_deeplink`, `run_osascript` with `--`, `clean_summary`/`clean_body`, the `\x1f`/`\x1e` control-char framing pattern from notes). No new dependencies.

**Tech Stack:** Python 3.12, FastMCP 2.0, PyObjC-free osascript, pytest, ruff, `uv`.

## Global Constraints

- **NEVER send.** No `send` verb in any template. Reply/draft are draft-and-open only.
- All native access via `runtime.run_osascript` (which appends `--`); user input via **argv or a tempfile — never string-interpolated** into a script.
- Every osascript template carries `with timeout of 120 seconds`.
- Tools in `server.py` are thin dispatch; all logic in the adapter. Typed errors from the runtime taxonomy so `server._guard` surfaces them.
- Unit tests mock `run_osascript` (no real Mail). Real-Mail tests are `@pytest.mark.integration` (NOT run in CI).
- ruff: line-length 88 (counts CHARACTERS); `E,F,I,UP,B,SIM`. Auto-format first, then hand-trim residual E501.
- Branch `feature/roadmap-0.5.0`; PR #74. Never merge/force-push; never stage the root `DESIGN.md`.
- **Per-issue gate before commit:** `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` all green; then run the multi-agent adversarial review workflow over that issue's diff and fix every confirmed finding (with a test) before committing. Report on the issue + append a line to PR #74; do NOT close the issue.
- gh active account must be `elfensky` before any push (`gh auth switch --user elfensky`).

## File Structure

- **Modify** `mac_mcp/adapters/mail.py` — add `_ATTACHMENTS` template + `_parse_attachments` + `MailAdapter.list_attachments`; make `create_draft` atomic and return a locator dict; add `_REPLY` template + `_build_quote` + `MailAdapter.reply`.
- **Modify** `mac_mcp/server.py` — add `mail_attachments` tool; update `create_draft` tool (returns a dict); add `mail_reply` tool.
- **Modify** `tests/test_mail.py` — unit tests for all three (mock `run_osascript`).
- **Modify** `tests/test_integration.py` — `@integration` tests + document the manual send-check.
- **Modify** `tests/test_tool_annotations.py` — register the new tools in `_PERMISSION` (Automation) and (for reply) `_ADDITIVE_TOOLS`.

---

## Task 1 — #45 `list_attachments(mailbox, query)` (safe READ, built first)

**Files:**
- Modify: `mac_mcp/adapters/mail.py` (add template, parser, method)
- Modify: `mac_mcp/server.py` (add `mail_attachments` tool)
- Test: `tests/test_mail.py`, `tests/test_integration.py`, `tests/test_tool_annotations.py`

**Interfaces:**
- Consumes: `system_mailbox_names(canonical) -> tuple[str,...]`, `run_osascript`, `clean_summary`, `MAX_MAILS`.
- Produces: `MailAdapter.list_attachments(mailbox: str, query: str = "") -> list[dict]` where each dict is `{"summary": str, "attachments": list[dict]}` and each attachment is `{"name": str, "size": int | None, "downloaded": bool | None}`. Server tool `mail_attachments(mailbox, query)`.

- [ ] **Step 1: Write the failing parser test**

In `tests/test_mail.py`:
```python
def test_parse_attachments_groups_by_message():
    from mac_mcp.adapters.mail import _parse_attachments

    us, rs = "\x1f", "\x1e"
    raw = (
        f"Logo files{us}LOGO.zip{us}1200000{us}true{us}spec.pdf{us}0{us}false{rs}"
        f"No attach subject{rs}"
    )
    out = _parse_attachments(raw)
    assert out[0]["summary"] == "Logo files"
    assert out[0]["attachments"] == [
        {"name": "LOGO.zip", "size": 1200000, "downloaded": True},
        {"name": "spec.pdf", "size": 0, "downloaded": False},
    ]
    assert out[1]["summary"] == "No attach subject"
    assert out[1]["attachments"] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_mail.py::test_parse_attachments_groups_by_message -v`
Expected: FAIL (`cannot import name '_parse_attachments'`).

- [ ] **Step 3: Add the template + parser to `mail.py`**

Add near the other templates:
```python
# list_attachments (#45): attachments of messages in a mailbox matching a subject query.
# Mailbox addressing is locale-aware — the caller passes the canonical name and the
# localized candidates (system_mailbox_names); the script uses the unified `inbox`
# accessor for inbox, else the first account mailbox whose name matches a candidate (so
# Drafts/Sent resolve on a non-English Mac). Fields framed with US (\x1f) / RS (\x1e):
# per record = subject, then (name, size, downloaded) TRIPLES per attachment. Output
# capped at maxN records. with timeout (#56). All inputs via argv (no interpolation).
_ATTACHMENTS = """on run argv
  set q to item 1 of argv
  set maxN to (item 2 of argv) as integer
  set canon to item 3 of argv
  set us to character id 31
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    if canon is "inbox" then
      set mb to inbox
    else
      set mb to missing value
      repeat with acc in accounts
        repeat with i from 4 to (count of argv)
          try
            set mb to mailbox (item i of argv) of acc
            exit repeat
          end try
        end repeat
        if mb is not missing value then exit repeat
      end repeat
      if mb is missing value then error "mailbox not found for " & canon
    end if
    repeat with m in (messages of mb whose subject contains q)
      set c to c + 1
      if c > maxN then exit repeat
      set out to out & (subject of m)
      repeat with a in (mail attachments of m)
        set aSize to ""
        try
          set aSize to (file size of a) as text
        end try
        set aDown to ""
        try
          set aDown to (downloaded of a) as text
        end try
        set out to out & us & (name of a) & us & aSize & us & aDown
      end repeat
      set out to out & rs
    end repeat
  end tell
  end timeout
  return out
end run"""


def _parse_attachments(raw: str) -> list[dict]:
    """Parse the _ATTACHMENTS payload: RS-separated records, each US-separated as
    subject then (name, size, downloaded) triples. Malformed/partial trailing records
    are skipped."""
    out = []
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f")
        summary = clean_summary(parts[0])
        atts = []
        rest = parts[1:]
        for i in range(0, len(rest) - 2, 3):
            name = rest[i].strip()
            if not name:
                continue
            size_s = rest[i + 1].strip()
            down_s = rest[i + 2].strip().lower()
            atts.append(
                {
                    "name": clean_summary(name),
                    "size": int(size_s) if size_s.isdigit() else None,
                    "downloaded": (down_s == "true")
                    if down_s in ("true", "false")
                    else None,
                }
            )
        out.append({"summary": summary or "(no subject)", "attachments": atts})
    return out
```

- [ ] **Step 4: Run the parser test to verify it passes**

Run: `uv run pytest tests/test_mail.py::test_parse_attachments_groups_by_message -v`
Expected: PASS.

- [ ] **Step 5: Write the failing method test**

In `tests/test_mail.py`:
```python
def test_list_attachments_resolves_mailbox_and_caps(monkeypatch):
    import mac_mcp.adapters.mail as mail

    captured = {}

    def fake(script, *args):
        captured["script"] = script
        captured["args"] = args
        return "Logo files\x1fLOGO.zip\x1f100\x1ftrue\x1e"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().list_attachments("drafts", "Logo")
    # canonical + localized candidates are passed via argv (Drafts is locale-aware)
    assert captured["args"][0] == "Logo"  # query
    assert captured["args"][2] == "drafts"  # canonical
    assert "Drafts" in captured["args"][3:]  # a localized candidate
    assert out == [
        {"summary": "Logo files", "attachments": [
            {"name": "LOGO.zip", "size": 100, "downloaded": True}]}
    ]


def test_list_attachments_unknown_mailbox_raises():
    from mac_mcp.adapters.mail import MailAdapter

    import pytest

    with pytest.raises(ValueError, match="unknown system mailbox"):
        MailAdapter().list_attachments("nope", "x")
```

- [ ] **Step 6: Run to verify it fails**

Run: `uv run pytest tests/test_mail.py -k list_attachments -v`
Expected: FAIL (`AttributeError: ... has no attribute 'list_attachments'`).

- [ ] **Step 7: Implement the method on `MailAdapter`**

In `mail.py`, add to `MailAdapter`:
```python
    def list_attachments(self, mailbox: str, query: str = "") -> list[dict]:
        """List attachments of messages in `mailbox` (canonical inbox/sent/drafts/trash/
        junk) whose subject contains `query`. Works for Drafts (no message-id needed) and
        on non-English Macs (localized names via system_mailbox_names). Returns up to
        MAX_MAILS records: [{"summary", "attachments": [{"name","size","downloaded"}]}].
        A read — never mutates."""
        candidates = system_mailbox_names(mailbox)  # raises on unknown canonical
        canon = mailbox.strip().lower()
        raw = run_osascript(
            _ATTACHMENTS, query.strip(), str(MAX_MAILS), canon, *candidates
        )
        return _parse_attachments(raw)[:MAX_MAILS]
```
Add `system_mailbox_names` is already module-local; ensure `MAX_MAILS` and `clean_summary` are imported (they are).

- [ ] **Step 8: Run the method tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k list_attachments -v`
Expected: PASS.

- [ ] **Step 9: Add the server tool**

In `server.py`, near the mail tools:
```python
    @mcp.tool
    def mail_attachments(mailbox: str, query: str = "") -> list[dict]:
        """List attachments on messages in a Mail mailbox (Automation).

        mailbox: canonical system mailbox — "inbox" | "sent" | "drafts" | "trash" |
        "junk" (localized automatically). query: optional subject substring. Use this to
        confirm an attachment landed on a DRAFT (drafts have no stable id). Returns
        [{summary, attachments: [{name, size, downloaded}]}], bounded.
        """
        return _guard(lambda: mail_adapter.list_attachments(mailbox, query))
```
(Match the existing registration style — `mail_adapter`, `_guard`, decorator — used by the other mail tools.)

- [ ] **Step 10: Register permission in tool-annotations test**

In `tests/test_tool_annotations.py`, add `"mail_attachments": "Automation"` to the `_PERMISSION` map (the docstring already contains the "Automation" keyword).

- [ ] **Step 11: Add the integration test**

In `tests/test_integration.py`:
```python
@pytest.mark.integration
def test_list_attachments_finds_draft_attachment(created):
    """#45: create a draft with an attachment, list it from Drafts, confirm it appears.
    Needs Automation access for Mail."""
    from mac_mcp.adapters.mail import MailAdapter
    from mac_mcp.runtime import run_osascript

    subj = "mac-mcp-test: attach (safe to delete)"
    # create a draft with an attachment via osascript (test-only helper)
    make = (
        "on run argv\n"
        '  tell application "Mail"\n'
        "    set d to make new outgoing message with properties "
        "{subject:(item 1 of argv), visible:false}\n"
        "    tell content of d to make new attachment with properties "
        "{file name:(POSIX file (item 2 of argv))}\n"
        "    save d\n"
        "  end tell\n"
        "end run"
    )
    # a small real file to attach
    import tempfile, os
    fd, path = tempfile.mkstemp(prefix="mac-mcp-itest-", suffix=".txt")
    os.write(fd, b"hello"); os.close(fd)
    try:
        run_osascript(make, subj, path)
        recs = MailAdapter().list_attachments("drafts", "mac-mcp-test: attach")
        names = [a["name"] for r in recs for a in r["attachments"]]
        assert any(path.split("/")[-1] in n or n.endswith(".txt") for n in names)
    finally:
        os.unlink(path)
        run_osascript(
            "on run argv\n"
            '  tell application "Mail"\n'
            "    repeat with acc in accounts\n"
            "      try\n"
            "        delete (messages of (mailbox \"Drafts\" of acc) whose subject is "
            "(item 1 of argv))\n"
            "      end try\n"
            "    end repeat\n"
            "  end tell\n"
            "end run",
            subj,
        )
```

- [ ] **Step 12: Verify green + format**

Run: `uv run ruff format mac_mcp/adapters/mail.py mac_mcp/server.py tests/test_mail.py tests/test_integration.py tests/test_tool_annotations.py`
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; integration deselected.

- [ ] **Step 13: Adversarial review gate**

Generate the diff for this task (`git diff -- mac_mcp tests`), run the multi-agent adversarial review workflow (plain JS, single quotes) with lenses: correctness/safety, osascript/parsing edge cases, mailbox-addressing behavior change, test adequacy. Fix every confirmed finding + add a test per fix; re-verify green.

- [ ] **Step 14: Commit + report**

```bash
gh auth switch --user elfensky
git add mac_mcp/adapters/mail.py mac_mcp/server.py tests/test_mail.py tests/test_integration.py tests/test_tool_annotations.py
git commit -m "feat(mail): list_attachments by mailbox+query (#45)"
git push origin feature/roadmap-0.5.0
```
Comment on #45 (what shipped, sha, review outcome) + append a line to PR #74. Do NOT close #45.

---

## Task 2 — #43/#44 atomic `create_draft` + locator dict

**Files:**
- Modify: `mac_mcp/adapters/mail.py` (`_CREATE_DRAFT` template + `create_draft`)
- Modify: `mac_mcp/server.py` (`create_draft` tool return type)
- Test: `tests/test_mail.py`, `tests/test_integration.py`

**Interfaces:**
- Consumes: `run_osascript`, `tempfile`.
- Produces: `MailAdapter.create_draft(to, subject, body) -> dict` = `{"created": True, "subject": str, "mailbox": "Drafts", "note": str}`. Server `create_draft` returns that dict.

- [ ] **Step 1: Write the failing atomicity + return test**

In `tests/test_mail.py`:
```python
def test_create_draft_returns_locator_dict(monkeypatch):
    import mac_mcp.adapters.mail as mail

    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    out = mail.MailAdapter().create_draft("x@example.com", "Hi", "body")
    assert out["created"] is True
    assert out["mailbox"] == "Drafts"
    assert out["subject"] == "Hi"
    assert "no stable id" in out["note"].lower()


def test_create_draft_cleanup_on_failure_is_in_script(monkeypatch):
    # atomicity (#44) is enforced INSIDE the osascript: assert the template deletes the
    # partial outgoing message on error (the script contains a delete in its error path).
    from mac_mcp.adapters.mail import _CREATE_DRAFT

    assert "delete" in _CREATE_DRAFT
    assert "on error" in _CREATE_DRAFT
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mail.py -k create_draft -v`
Expected: FAIL (`create_draft` returns `None`; `_CREATE_DRAFT` has no error path yet).

- [ ] **Step 3: Make `_CREATE_DRAFT` atomic**

Replace the `_CREATE_DRAFT` template body so the outgoing message is deleted if any
step after creation fails:
```python
_CREATE_DRAFT = """on run argv
  set recipientAddr to item 1 of argv
  set subj to item 2 of argv
  set bodyText to (read (POSIX file (item 3 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:true}
    try
      set subject of msg to subj
      set content of msg to bodyText
      tell msg to make new to recipient with properties {address:recipientAddr}
      activate
    on error errMsg
      delete msg
      error errMsg
    end try
  end tell
  end timeout
end run"""
```

- [ ] **Step 4: Return the locator dict from `create_draft`**

Change `create_draft`'s signature/return in `mail.py`:
```python
    def create_draft(self, to: str, subject: str, body: str) -> dict:
        """Create a Mail draft and OPEN it for the human to review/send — NEVER sends.
        Atomic (#44): if any step after creation fails, the script deletes the partial
        draft before erroring, so a retry can't strand a duplicate. Returns a locator
        (#43): an unsent draft has no stable Message-ID (Mail stamps it only on send), so
        we return where to find it, not a fabricated id."""
        addr = to.strip()
        if not addr:
            raise ValueError("create_draft needs a recipient address (to)")
        fd, path = tempfile.mkstemp(prefix="mac-mcp-draft-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body or "")
            run_osascript(_CREATE_DRAFT, addr, subject or "", path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        return {
            "created": True,
            "subject": subject or "",
            "mailbox": "Drafts",
            "note": "unsent drafts have no stable id; find it in Drafts",
        }
```

- [ ] **Step 5: Run to verify tests pass**

Run: `uv run pytest tests/test_mail.py -k create_draft -v`
Expected: PASS.

- [ ] **Step 6: Update the server tool return + docstring**

In `server.py`, change the `create_draft` tool to `-> dict` and return the adapter dict
via `_guard`; update the docstring to say it returns a locator dict (keep the "Automation"
keyword and the never-sends note). Confirm `create_draft` stays in `_ADDITIVE_TOOLS` and
its `_PERMISSION` entry is unchanged in `tests/test_tool_annotations.py`.

- [ ] **Step 7: Update the integration test to assert the dict + never-sends**

Extend `test_mail_create_draft_opens_and_never_sends` to also assert the returned dict:
```python
    result = MailAdapter().create_draft(
        "nobody@example.invalid", subj, "test body — do not send"
    )
    assert result["created"] is True and result["mailbox"] == "Drafts"
```
(Keep the existing outgoing-message count + delete cleanup asserting nothing was sent.)

- [ ] **Step 8: Verify green + format**

Run: `uv run ruff format mac_mcp/... tests/...` then
`uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 9: Adversarial review gate**

Diff → multi-agent review (lenses: correctness/safety of the delete-on-error path, osascript error handling, the return-type change's downstream effect, test adequacy). Fix confirmed findings + tests; re-verify.

- [ ] **Step 10: Commit + report**

```bash
gh auth switch --user elfensky
git add mac_mcp/adapters/mail.py mac_mcp/server.py tests/test_mail.py tests/test_integration.py
git commit -m "feat(mail): atomic create_draft + locator dict (#43, #44)"
git push origin feature/roadmap-0.5.0
```
Comment on #43 and #44 (sha, review outcome) + append a line to PR #74. Do NOT close them.

---

## Task 3 — #42/#46 `reply(message_id, reply_body, include_quote=True)`

**Files:**
- Modify: `mac_mcp/adapters/mail.py` (`_REPLY` template, `_build_quote`, `reply`)
- Modify: `mac_mcp/server.py` (`mail_reply` tool)
- Test: `tests/test_mail.py`, `tests/test_integration.py`, `tests/test_tool_annotations.py`

**Interfaces:**
- Consumes: `run_osascript`, `clean_body`, `_MISSING_VALUE`, `NativeError`.
- Produces: `MailAdapter.reply(message_id: str, reply_body: str, include_quote: bool = True) -> dict` = same locator dict shape as `create_draft`. Server `mail_reply(message_id, reply_body, include_quote=True)`.

- [ ] **Step 1: Write the failing quote-builder test**

In `tests/test_mail.py`:
```python
def test_build_quote_prefixes_and_headers():
    from mac_mcp.adapters.mail import _build_quote

    q = _build_quote("Jane <j@x.com>", "2026-07-01", "line one\nline two")
    assert "On 2026-07-01, Jane <j@x.com> wrote:" in q
    assert "> line one" in q and "> line two" in q


def test_reply_composes_body_and_targets_id(monkeypatch):
    import mac_mcp.adapters.mail as mail

    calls = []

    def fake(script, *args):
        calls.append((script, args))
        # first call fetches the original (sender/date/body); return a framed triple
        if "message id" in script and "content" in script and "reply" not in script:
            return "Jane <j@x.com>\x1f2026-07-01\x1foriginal body"
        return ""

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().reply("<abc@x>", "my reply", include_quote=True)
    assert out["created"] is True
    # the reply script received the message-id and a body containing reply + quote
    reply_call = [c for c in calls if "reply" in c[0]][0]
    assert "abc@x" in reply_call[1][0]
    assert "my reply" in reply_call[1][1]
    assert "> original body" in reply_call[1][1]


def test_reply_without_quote_omits_original(monkeypatch):
    import mac_mcp.adapters.mail as mail

    monkeypatch.setattr(
        mail, "run_osascript",
        lambda s, *a: ("Jane\x1f2026-07-01\x1forig" if "reply" not in s else ""),
    )
    # capture the reply body
    bodies = []
    real = mail.run_osascript

    def cap(s, *a):
        if "reply" in s:
            bodies.append(a[1])
        return real(s, *a)

    monkeypatch.setattr(mail, "run_osascript", cap)
    mail.MailAdapter().reply("<abc@x>", "just this", include_quote=False)
    assert bodies and "just this" in bodies[0] and ">" not in bodies[0]


def test_reply_empty_args_raise():
    import pytest
    from mac_mcp.adapters.mail import MailAdapter

    with pytest.raises(ValueError):
        MailAdapter().reply("", "body")
    with pytest.raises(ValueError):
        MailAdapter().reply("<abc@x>", "  ")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mail.py -k reply -v`
Expected: FAIL (`_build_quote` / `reply` not defined).

- [ ] **Step 3: Add the fetch-original template + reply template + quote builder**

In `mail.py`:
```python
# reply (#42/#46): fetch the original's sender/date/plaintext by message-id (US-framed),
# so Python can build the quoted block deterministically (Mail's auto-quote is NOT visible
# via the content property — spike 2026-07-11). Scoped to inbox, like _BODY.
_ORIGINAL = """on run argv
  set mid to item 1 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set m to item 1 of matches
    set snd to sender of m
    set dt to (date received of m) as text
    set c to content of m
    if c is missing value then set c to ""
    return snd & us & dt & us & c
  end tell
  end timeout
end run"""

# reply builds a real reply via Mail's NATIVE reply verb (Mail owns In-Reply-To/References
# threading — the only mechanism that threads; make-new-outgoing can't set headers, spike
# 2026-07-11). The body (reply text + our quote) is set on the returned outgoing message —
# keystroke-free (satisfies #46; no .eml). A window opens for the HUMAN to review/send.
# NEVER sends. Atomic (#44): delete the draft on any post-creation failure. body via
# tempfile as «class utf8»; message-id via argv.
_REPLY = """on run argv
  set mid to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set r to reply (item 1 of matches) opening window yes
    try
      set content of r to bodyText
    on error errMsg
      delete r
      error errMsg
    end try
  end tell
  end timeout
end run"""


def _build_quote(sender: str, date_str: str, original_body: str) -> str:
    """Standard reply quote: `On <date>, <sender> wrote:` then the original body, each
    line `> `-prefixed. Bounded via clean_body so a huge original can't bloat the draft."""
    bounded = clean_body(original_body)
    quoted = "\n".join("> " + line for line in bounded.splitlines())
    return f"On {date_str}, {sender} wrote:\n{quoted}"
```

- [ ] **Step 4: Implement `reply` on `MailAdapter`**

```python
    def reply(
        self, message_id: str, reply_body: str, include_quote: bool = True
    ) -> dict:
        """Reply to an inbox message by its RFC822 message-id: opens a threaded draft for
        the human to review/send — NEVER sends. Uses Mail's native reply verb so
        In-Reply-To/References are set by Mail (real Gmail/Outlook threading). include_
        quote appends `On <date>, <sender> wrote:` + the `> `-quoted original. Keystroke-
        free (#46); atomic (#44). Returns the same locator dict as create_draft (an unsent
        draft has no stable id)."""
        mid = message_id.strip().lstrip("<").rstrip(">")
        if not mid:
            raise ValueError("reply needs the original message's id")
        if not reply_body.strip():
            raise ValueError("reply needs a non-empty reply_body")
        body = reply_body
        if include_quote:
            raw = run_osascript(_ORIGINAL, mid)
            if raw.strip() and raw.strip() != _MISSING_VALUE:
                sender, _, rest = raw.partition("\x1f")
                date_str, _, original = rest.partition("\x1f")
                body = reply_body + "\n\n" + _build_quote(sender, date_str, original)
        fd, path = tempfile.mkstemp(prefix="mac-mcp-reply-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            run_osascript(_REPLY, mid, path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        return {
            "created": True,
            "subject": "(reply)",
            "mailbox": "Drafts",
            "note": "reply draft opened for review; unsent drafts have no stable id",
        }
```

- [ ] **Step 5: Run to verify the unit tests pass**

Run: `uv run pytest tests/test_mail.py -k reply -v`
Expected: PASS. (Adjust the fake-matching in the tests if the branch predicate differs; the intent is: quote path calls `_ORIGINAL` then `_REPLY`, no-quote path calls only `_REPLY`.)

- [ ] **Step 6: Add the server tool**

In `server.py`:
```python
    @mcp.tool
    def mail_reply(
        message_id: str, reply_body: str, include_quote: bool = True
    ) -> dict:
        """Reply to an inbox message, opening a threaded draft for review (Automation).
        NEVER sends. message_id: the RFC822 id from a mail read. Mail sets the threading
        headers natively; include_quote appends the quoted original. Returns a locator
        dict (unsent drafts have no stable id).
        """
        return _guard(
            lambda: mail_adapter.reply(message_id, reply_body, include_quote)
        )
```
Add `"mail_reply"` to `_ADDITIVE_TOOLS` (it creates a draft, additive/non-destructive) and `"mail_reply": "Automation"` to `_PERMISSION` in `tests/test_tool_annotations.py`.

- [ ] **Step 7: Add the integration test + document the manual send-check**

In `tests/test_integration.py`:
```python
@pytest.mark.integration
def test_mail_reply_opens_threaded_draft_and_never_sends():
    """#42/#46: reply to a real inbox message → a draft exists UNSENT (outgoing message)
    with our body; delete it; confirm nothing sent. Threading headers can only be proved
    post-send — see the manual step in the PR's 'needs manual verification'."""
    from mac_mcp.adapters.mail import MailAdapter
    from mac_mcp.runtime import run_osascript

    # newest inbox message id
    mid = run_osascript(
        "tell application \"Mail\" to return message id of "
        "(item 1 of (messages of inbox))"
    ).strip()
    before = int(run_osascript(
        "tell application \"Mail\" to return (count of outgoing messages) as text"
    ))
    MailAdapter().reply(mid, "mac-mcp itest reply — do not send", include_quote=True)
    try:
        after = int(run_osascript(
            "tell application \"Mail\" to return (count of outgoing messages) as text"
        ))
        assert after == before + 1  # a draft was created, not sent
    finally:
        run_osascript(
            "on run argv\n"
            '  tell application "Mail"\n'
            "    repeat with m in outgoing messages\n"
            "      if content of m contains (item 1 of argv) then delete m\n"
            "    end repeat\n"
            "  end tell\n"
            "end run",
            "mac-mcp itest reply",
        )
```

- [ ] **Step 8: Verify green + format**

Run: `uv run ruff format` on the touched files, then
`uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 9: Adversarial review gate**

Diff → multi-agent review (lenses: correctness/safety incl. never-send + atomic delete, osascript/quote-building edge cases, the message-id lookup, test adequacy). Fix confirmed findings + tests; re-verify.

- [ ] **Step 10: Commit + report**

```bash
gh auth switch --user elfensky
git add mac_mcp/adapters/mail.py mac_mcp/server.py tests/test_mail.py tests/test_integration.py tests/test_tool_annotations.py
git commit -m "feat(mail): threaded reply via native reply verb (#42, #46)"
git push origin feature/roadmap-0.5.0
```
Comment on #42 and #46 (sha, review outcome, and the manual send-check needed for threading) + append a line to PR #74 including the manual-verification item. Do NOT close them.

---

## Self-Review

**Spec coverage:**
- #42 (quote + threading) → Task 3 (`reply` via native verb, `_build_quote`, In-Reply-To/References set by Mail). ✓
- #43 (return created id) → Task 2 (locator dict; honest no-stable-id note). ✓
- #44 (no stray draft) → Task 2 (atomic delete-on-error in `_CREATE_DRAFT`) + Task 3 (same in `_REPLY`). ✓
- #45 (attachments + mailbox param) → Task 1 (`list_attachments(mailbox, query)`). ✓
- #46 (keystroke-free open) → Task 3 (native reply verb, no keystrokes, no `.eml`). ✓

**Placeholder scan:** every code step contains full code; commands have expected output; no TBD/TODO. The one soft spot (Task 3 Step 5) tells the implementer to adjust the fake predicate to match the branch, not to invent behavior — acceptable.

**Type consistency:** `create_draft` and `reply` both return the locator dict `{created, subject, mailbox, note}`; `list_attachments` returns `[{summary, attachments:[{name,size,downloaded}]}]`; `_parse_attachments` matches that shape; server tools return the same. Consistent across tasks.

**Known on-device unknowns (verified by the integration steps, not hand-waved):**
- Mailbox addressing for Drafts/Sent across accounts (Task 1 integration test).
- Whether the open compose window reflects the programmatically-set content (Task 3 integration test / manual review).
- Threading headers exist only post-send → the single manual send-to-self check.
