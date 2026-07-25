# Mail outbound & the send gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-adapter outbound gate (`MACOS_APPS_ALLOW_SEND`) and, behind it, Mail's first
sending tools — plus an ungated drafts list/delete.

**Architecture:** One predicate + one decorator in `server.py`, mirroring the existing `_read_only()`
seam: gated tools are **absent at registration**, never registered-and-erroring. Adapter methods go
in `adapters/mail.py`; `server.py` stays thin dispatch. Every AppleScript verb used here was
device-verified on 2026-07-25 — see the spec's "AppleScript findings" section before touching a
script.

**Tech Stack:** Python 3.12+, FastMCP, `uv`, pytest, ruff. Native access via
`runtime.run_osascript(script, *argv)` and `runtime.body_file`.

**Spec:** [`docs/superpowers/specs/2026-07-25-mail-outbound-send-gate-design.md`](../specs/2026-07-25-mail-outbound-send-gate-design.md)

## Global Constraints

- Line length **88**; ruff rules `E, F, I, UP, B, SIM`. Run `uv run ruff format .` before each commit.
- **No business logic in the tool layer.** `server.py` tools are one-line dispatch to `_mail`.
- **User input via argv or a tempfile — NEVER interpolated into an AppleScript string.** Bodies go
  through `body_file(...)` and are read as `«class utf8»`; addresses/subjects go via argv.
- **Framing (#68):** any multi-field AppleScript payload uses `US`/`RS` from `text.py` with the
  shared `STRIP_FRAMING` handler applied to every free-text field, parsed with `split_framed`.
  Never hard-code `\x1f`/`\x1e`; never re-declare the handler.
- **`whose` is unreliable on the Drafts mailbox** (`-1728`). Address drafts by iterating
  `message i of dm` and comparing `message id`. Deleting while iterating invalidates the collection
  — iterate **in reverse by index**.
- **Never construct an `outgoing message` on a dry-run path** — `delete msg` does not reliably
  remove Mail's autosaved Drafts copy.
- `Pointer.id` for mail is always the RFC822 `message id`, never the AppleScript integer `id`.
- Verification before any "done" claim: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
- Integration tests are `@pytest.mark.integration`, on-device only, **never CI**, and any send test
  targets **only `andrei@lav.ren`** (the operator's own address).

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `macos_apps_mcp/server.py` | gate predicate, `_send_tool`, tool registration | modify |
| `macos_apps_mcp/adapters/mail.py` | AppleScript + adapter methods | modify |
| `tests/test_server.py` | gate predicate parse table | modify |
| `tests/test_mail.py` | adapter unit tests | modify |
| `tests/test_tool_annotations.py` | permission/annotation maps | modify |
| `tests/integration/test_mail_outbound.py` | on-device send tests | create |
| `README.md`, `CHANGELOG.md` | docs | modify |

---

### Task 1: The send gate (#104)

**Files:**
- Modify: `macos_apps_mcp/server.py` (after `_read_only()`, ~line 68, and after
  `_DESTRUCTIVE_ANNOTATIONS`, ~line 102)
- Test: `tests/test_server.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `_read_only()`, `_WRITE_TOOLS`, `_SNAPSHOT_SOURCES`, `_guard`, `Snapshotter` (all
  already in `server.py`).
- Produces: `_allow_send(adapter: str) -> bool`, `_SEND_ANNOTATIONS: dict`,
  `_send_tool(adapter: str, *, snapshot: Snapshotter | None = None)` — the decorator Tasks 4 and 5
  register their tools with.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
@pytest.mark.parametrize(
    "val,want",
    [
        ("", False),
        ("0", False),
        ("off", False),
        ("messages", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("all", True),
        ("mail", True),
        ("mail,messages", True),
        ("MAIL", True),
        (" mail , ", True),
        ("mail,,", True),
    ],
)
def test_allow_send_parse(monkeypatch, val, want):
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", val)
    assert srv._allow_send("mail") is want


def test_allow_send_unset_is_false(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    assert srv._allow_send("mail") is False


def test_read_only_beats_allow_send(monkeypatch):
    # READ_ONLY is the safe-deploy guard — a send tier cannot punch through it.
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "all")
    assert srv._allow_send("mail") is False


def test_allow_send_is_per_adapter(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)
    monkeypatch.setenv("MACOS_APPS_ALLOW_SEND", "mail")
    assert srv._allow_send("mail") is True
    assert srv._allow_send("messages") is False


def test_send_annotations_are_destructive_and_open_world():
    assert srv._SEND_ANNOTATIONS == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -k "allow_send or send_annotations" -v`
Expected: FAIL with `AttributeError: module 'macos_apps_mcp.server' has no attribute '_allow_send'`

- [ ] **Step 3: Implement the gate**

In `macos_apps_mcp/server.py`, immediately after `_read_only()`:

```python
def _allow_send(adapter: str) -> bool:
    """True when OUTBOUND is enabled for ``adapter`` (#104).

    ``MACOS_APPS_ALLOW_SEND`` is unset by default — "never sends" stays the default, but
    absence is a GATE, not a ceiling. ``1``/``true``/``yes``/``all`` enable every adapter;
    a comma list (``mail,messages``) enables named ones, so a user can accept Mail send
    (reviewable, leaves a Sent record) while refusing iMessage send (instant, social, no
    undo). ``MACOS_APPS_READ_ONLY`` wins unconditionally — it is the safe-deploy guard.
    Read at registration time, like ``_read_only()``: set it before launching the server.
    """
    if _read_only():
        return False
    val = os.environ.get("MACOS_APPS_ALLOW_SEND", "").strip().lower()
    if val in ("1", "true", "yes", "all"):
        return True
    return adapter in {p.strip() for p in val.split(",") if p.strip()}
```

After `_DESTRUCTIVE_ANNOTATIONS`:

```python
# Outbound leaves this machine — a sent mail cannot be recalled by any tool here. MCP's
# openWorldHint is exactly that signal ("interacts with external entities"), so a host can
# gate send_mail differently from delete_event, which is destructive but purely local.
_SEND_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "openWorldHint": True,
}
```

After `_additive_tool`:

```python
def _send_tool(adapter: str, *, snapshot: Snapshotter | None = None):
    """Register an OUTBOUND tool — absent unless MACOS_APPS_ALLOW_SEND names ``adapter``
    (#104). Annotated destructive + open-world (#57). ``snapshot``: as on ``_write_tool``,
    the adapter answering ``snapshot(id)`` for audit before-state on an id-addressed send
    (#67) — unused today, kept so #86/#84 cannot silently skip before-state capture."""

    def deco(f):
        if not _allow_send(adapter):
            return f
        _WRITE_TOOLS.add(f.__name__)
        if snapshot is not None:
            _SNAPSHOT_SOURCES[f.__name__] = snapshot
        return mcp.tool(annotations=_SEND_ANNOTATIONS)(_guard(f))

    return deco
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -k "allow_send or send_annotations" -v`
Expected: PASS (10+ tests)

- [ ] **Step 5: Document the gate in README**

In `README.md`, immediately after the "### Read-only mode" paragraph, add:

```markdown
### Outbound (send) mode

Sending is **off by default** — the server creates drafts and never sends. Set
`MACOS_APPS_ALLOW_SEND` to opt in, per adapter:

| Value | Effect |
|---|---|
| unset (default) | no send tools are registered at all |
| `mail` | Mail outbound only (`send_mail`, `reply_all`, `forward_mail`) |
| `mail,messages` | named adapters (comma list) |
| `1` / `true` / `yes` / `all` | every adapter's outbound |

`MACOS_APPS_READ_ONLY` always wins: with both set, no send tools are registered.

Send tools take `dry_run`, which **defaults to `True`** — deliberately inverted from the
id-addressed deletes. A delete targets an item a read already returned; a send *constructs* its
recipient, and a wrong recipient is the failure that matters. The dry run makes no call into Mail
at all and reports the resolved envelope; pass `dry_run=False` to actually send.
```

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add macos_apps_mcp/server.py tests/test_server.py README.md
git commit -m "feat(server): #104 per-adapter MACOS_APPS_ALLOW_SEND gate

Registration-time absence on the existing _read_only() seam; READ_ONLY wins
unconditionally. Send tools get openWorldHint — outbound leaves the machine,
unlike delete_event which is destructive but local.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `drafts` — list drafts as pointers (#82, ungated)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py` (script near `_CREATE_DRAFT`; methods on `MailAdapter`)
- Modify: `macos_apps_mcp/server.py` (tool near `create_draft`)
- Test: `tests/test_mail.py`, `tests/test_tool_annotations.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Pointer`, `_summary`, `_deeplink`, `clean_summary`, `split_framed`, `STRIP_FRAMING`,
  `US`, `RS`, `MAX_MAILS`, `run_osascript` — all already imported in `mail.py`.
- Produces: `MailAdapter.list_drafts() -> list[Pointer]`, `MailAdapter.snapshot(ident: str) ->
  Pointer | None` (satisfies the `Snapshotter` Protocol — Task 3 depends on it), and the `drafts`
  tool.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mail.py`:

```python
def test_list_drafts_parses_framed_records(monkeypatch):
    raw = (
        f"<a@b.com>{US}Q3 numbers{US}boss@corp.com{RS}"
        f"<c@d.com>{US}Lunch?{US}pal@example.org{RS}"
    )
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    out = mail.MailAdapter().list_drafts()
    assert [p.id for p in out] == ["<a@b.com>", "<c@d.com>"]
    assert out[0].summary == "Q3 numbers — to boss@corp.com"
    assert out[0].deeplink.startswith("message://")


def test_list_drafts_skips_records_without_message_id(monkeypatch):
    # a draft with no Message-ID has no stable citation — never emit a garbage id.
    raw = f"missing value{US}No id{US}x@y.com{RS}<ok@z>{US}Fine{US}a@b.com{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert [p.id for p in mail.MailAdapter().list_drafts()] == ["<ok@z>"]


def test_list_drafts_empty_mailbox(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    assert mail.MailAdapter().list_drafts() == []


def test_list_drafts_summary_without_recipient(monkeypatch):
    raw = f"<a@b>{US}Just a subject{US}{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert mail.MailAdapter().list_drafts()[0].summary == "Just a subject"


def test_snapshot_returns_pointer_for_known_draft(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    monkeypatch.setattr(mail, "run_osascript", lambda *a: raw)
    assert mail.MailAdapter().snapshot("<a@b>").summary == "Q3 numbers — to boss@corp.com"


def test_snapshot_returns_none_for_unknown_id(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    assert mail.MailAdapter().snapshot("<nope@nowhere>") is None
```

Ensure the test module imports what it needs (add to the existing import block if absent — Tasks 4
and 5 rely on `nullcontext` and `pytest` too):

```python
from contextlib import nullcontext

import pytest

from macos_apps_mcp.adapters import mail
from macos_apps_mcp.text import RS, US
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail.py -k "drafts or snapshot" -v`
Expected: FAIL with `AttributeError: 'MailAdapter' object has no attribute 'list_drafts'`

- [ ] **Step 3: Add the AppleScript**

In `macos_apps_mcp/adapters/mail.py`, after `_CREATE_DRAFT`:

```python
# drafts (#82): list the Drafts mailbox as US/RS-framed (message id, subject, first
# recipient) records. Iterates BY INDEX rather than with a `whose` filter — on device,
# `messages of drafts mailbox whose subject is X` raised -1728 for a draft that
# demonstrably existed, while index access is reliable (spike 2026-07-25). Output is
# capped host-side at maxN, the _SEARCH idiom (#52). The first recipient is enough for a
# pointer summary; a draft's own sender is the user, so it carries no signal.
_DRAFTS = (
    STRIP_FRAMING
    + """

on run argv
  set maxN to (item 1 of argv) as integer
  set us to character id 31
  set rs to character id 30
  set out to ""
  set c to 0
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set n to count of (messages of dm)
    repeat with i from 1 to n
      set m to message i of dm
      set mid to message id of m
      if mid is not missing value and mid is not "" then
        set c to c + 1
        if c > maxN then exit repeat
        set subj to subject of m
        if subj is missing value then set subj to ""
        set rcpt to ""
        try
          set rcpt to (address of item 1 of (to recipients of m)) as text
        end try
        set out to out & (my stripFraming(mid)) & us & (my stripFraming(subj)) & ¬
          us & (my stripFraming(rcpt)) & rs
      end if
    end repeat
  end tell
  end timeout
  return out
end run"""
)
```

- [ ] **Step 4: Add the adapter methods**

In `mail.py`, add a module-level parser next to `_parse_search_results`:

```python
def _parse_draft_records(raw: str) -> list[Pointer]:
    """Parse the _DRAFTS payload: US-framed (message id, subject, first recipient)
    records. Records with no stable message-id are skipped — same rule as the inbox
    reads (#61): never emit a non-resolvable id."""
    out = []
    for fields in split_framed(raw):
        mid = fields[0].strip()
        if mid in ("", "missing value"):
            continue
        subject = fields[1] if len(fields) > 1 else ""
        rcpt = fields[2].strip() if len(fields) > 2 else ""
        who = f"to {rcpt}" if rcpt else ""
        out.append(
            Pointer(
                id=mid,
                summary=clean_summary(_summary(subject, who)),
                deeplink=_deeplink(mid),
            )
        )
    return out
```

On `MailAdapter`, after `create_draft`:

```python
    def list_drafts(self) -> list[Pointer]:
        """List the Drafts mailbox as pointers (id + "subject — to recipient"). A read —
        never mutates. Bounded to MAX_MAILS. Unlike the inbox reads this is NOT scoped to
        one account: `drafts mailbox` is Mail's unified, locale-independent accessor."""
        return _parse_draft_records(run_osascript(_DRAFTS, str(MAX_MAILS)))

    def snapshot(self, ident: str) -> Pointer | None:
        """Current Pointer for one draft, or None if the id no longer resolves — the
        before-state an id-addressed write needs for the audit trail (#67). Satisfies the
        Snapshotter Protocol."""
        mid = ident.strip()
        for p in self.list_drafts():
            if p.id == mid:
                return p
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k "drafts or snapshot" -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Register the tool**

In `macos_apps_mcp/server.py`, after `create_draft`:

```python
@_read_tool
def drafts() -> list[dict[str, str]]:
    """List Mail drafts as pointers (id + "subject — to recipient"), newest mailbox order,
    bounded. The id is the RFC822 message-id — pass it to delete_draft. Read-only; needs
    Automation access for Mail."""
    return [p.as_dict() for p in _mail.list_drafts()]
```

- [ ] **Step 7: Classify the tool**

In `tests/test_tool_annotations.py`, add to `_PERMISSION`:

```python
    "drafts": "Automation",
```

- [ ] **Step 8: Document in README**

In the Mail tool table in `README.md`, add a row:

```markdown
| `drafts` | — | list Mail drafts as pointers (id + subject — to recipient) |
```

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add macos_apps_mcp/adapters/mail.py macos_apps_mcp/server.py tests/ README.md
git commit -m "feat(mail): #82 drafts — list Mail drafts as pointers

Index-based iteration, not a \`whose\` filter: on device, \`messages of drafts
mailbox whose subject is X\` raised -1728 for a draft that existed.

Adds MailAdapter.snapshot() so the adapter satisfies the Snapshotter
Protocol, which delete_draft needs for audit before-state (#67).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `delete_draft` (#82, gated by READ_ONLY only)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py`
- Modify: `macos_apps_mcp/server.py`
- Test: `tests/test_mail.py`, `tests/test_tool_annotations.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `MailAdapter.snapshot` and `list_drafts` (Task 2), `_write_tool` (existing).
- Produces: `MailAdapter.delete_draft(ident: str, dry_run: bool = False) -> dict`, the
  `delete_draft` tool registered with `snapshot=_mail`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mail.py`:

```python
def test_delete_draft_dry_run_makes_no_native_call(monkeypatch):
    raw = f"<a@b>{US}Q3 numbers{US}boss@corp.com{RS}"
    calls = []

    def fake(script, *argv):
        calls.append(script)
        return raw

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().delete_draft("<a@b>", dry_run=True)
    assert out["dry_run"] is True
    assert out["would_delete"]["id"] == "<a@b>"
    # exactly one call — the snapshot read. Never the delete script.
    assert calls == [mail._DRAFTS]


def test_delete_draft_dry_run_unknown_id_raises(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    with pytest.raises(ValueError, match="no draft"):
        mail.MailAdapter().delete_draft("<nope@nowhere>", dry_run=True)


def test_delete_draft_deletes_by_message_id(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return f"<a@b>{US}Q3{US}x@y.com{RS}" if script is mail._DRAFTS else "deleted"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().delete_draft("<a@b>")
    assert out == {"deleted": True, "id": "<a@b>"}
    assert seen[mail._DELETE_DRAFT] == ("<a@b>",)


def test_delete_draft_rejects_empty_id():
    with pytest.raises(ValueError, match="draft id"):
        mail.MailAdapter().delete_draft("   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail.py -k delete_draft -v`
Expected: FAIL with `AttributeError: 'MailAdapter' object has no attribute 'delete_draft'`

- [ ] **Step 3: Add the AppleScript**

In `mail.py`, after `_DRAFTS`:

```python
# delete_draft (#82): resolve one draft by RFC822 message-id and delete it. Iterates
# IN REVERSE BY INDEX: deleting while iterating a forward collection invalidates the
# reference (-1728, device-verified), and a `whose` equality filter is unreliable on the
# Drafts mailbox. Returns immediately after the delete, so at most one is removed.
_DELETE_DRAFT = """on run argv
  set mid to item 1 of argv
  with timeout of 120 seconds
  tell application "Mail"
    set dm to drafts mailbox
    set n to count of (messages of dm)
    repeat with i from n to 1 by -1
      set m to message i of dm
      set thisId to message id of m
      if thisId is not missing value and (thisId as text) is mid then
        delete m
        return "deleted"
      end if
    end repeat
    error "no draft with that message id"
  end tell
  end timeout
end run"""
```

- [ ] **Step 4: Add the adapter method**

On `MailAdapter`, after `snapshot`:

```python
    def delete_draft(self, ident: str, dry_run: bool = False) -> dict:
        """Delete one draft by its RFC822 message-id (from `list_drafts`). ``dry_run=True``
        resolves the target and returns the Pointer that WOULD be deleted, no mutation —
        the `delete_event` shape. Raises if the id resolves to no draft, so a stale id
        fails loudly instead of silently deleting nothing."""
        mid = ident.strip()
        if not mid:
            raise ValueError(
                "delete_draft needs a draft id (the message-id from drafts)"
            )
        if dry_run:
            found = self.snapshot(mid)
            if found is None:
                raise ValueError(f"no draft with message id {mid!r}")
            return {"dry_run": True, "would_delete": found.as_dict()}
        run_osascript(_DELETE_DRAFT, mid)
        return {"deleted": True, "id": mid}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k delete_draft -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Register the tool**

In `server.py`, after `drafts`:

```python
@_write_tool(snapshot=_mail)
def delete_draft(id: str, dry_run: bool = False) -> dict:
    """Delete one Mail draft by its message-id (from drafts()). `dry_run=True` previews
    the draft that WOULD be deleted (pointer, no mutation). Destructive but LOCAL — this
    deletes an unsent draft, it never sends. Needs Automation access for Mail."""
    return _mail.delete_draft(id, dry_run=dry_run)
```

- [ ] **Step 7: Classify the tool**

In `tests/test_tool_annotations.py`: add `"delete_draft"` to the `_DESTRUCTIVE_TOOLS` frozenset, and
add to `_PERMISSION`:

```python
    "delete_draft": "Automation",
```

Do **not** add it to `envelope_only` in `test_every_write_tool_is_audit_classified` — it registers a
`_SNAPSHOT_SOURCES` entry, so that test passes only if it is absent from `envelope_only`.

- [ ] **Step 8: Document in README**

Add a row to the Mail tool table:

```markdown
| `delete_draft` | `id`, `dry_run` | delete one draft by message-id; `dry_run` previews |
```

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add macos_apps_mcp/adapters/mail.py macos_apps_mcp/server.py tests/ README.md
git commit -m "feat(mail): #82 delete_draft — id-addressed, dry-runnable, audited

Reverse-index iteration: deleting while iterating a forward AppleScript
collection invalidates the reference (-1728, device-verified).

Wired with snapshot=_mail so AuditMiddleware captures before-state (#67).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `send_mail` (#83, gated)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py`
- Modify: `macos_apps_mcp/server.py`
- Test: `tests/test_mail.py`, `tests/test_tool_annotations.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `_send_tool` (Task 1), `body_file`, `run_osascript`, `US`.
- Produces: `_split_addrs(value) -> list[str]`,
  `MailAdapter.send(to, subject, body, cc=None, bcc=None, html=False, from_address=None,
  dry_run=True) -> dict`, the `send_mail` tool.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mail.py`:

```python
def test_split_addrs_accepts_string_and_list():
    assert mail._split_addrs("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]
    assert mail._split_addrs(["a@b.com", " c@d.com "]) == ["a@b.com", "c@d.com"]
    assert mail._split_addrs(None) == []
    assert mail._split_addrs(" , ") == []


def test_send_dry_run_touches_nothing(monkeypatch):
    # A dry run must make NO native call: constructing an outgoing message can strand an
    # autosaved copy in Drafts even when the script deletes it (device-verified).
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().send(
        "a@b.com", "Hi", "body text", cc="c@d.com", from_address="me@corp.com"
    )
    assert out == {
        "dry_run": True,
        "would_send": {
            "to": ["a@b.com"],
            "cc": ["c@d.com"],
            "bcc": [],
            "from": "me@corp.com",
            "subject": "Hi",
            "body_chars": 9,
            "html": False,
        },
    }


def test_send_dry_run_reports_default_account_when_from_omitted(monkeypatch):
    monkeypatch.setattr(mail, "run_osascript", lambda *a: "")
    out = mail.MailAdapter().send("a@b.com", "Hi", "x")
    # Mail's default sender is NOT predictable from account order (device-verified), so
    # never report a computed guess.
    assert out["would_send"]["from"] == "(Mail default account)"


def test_send_passes_addresses_via_argv_us_joined(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen["script"], seen["argv"] = script, argv
        return "sent"

    monkeypatch.setattr(mail, "run_osascript", fake)
    out = mail.MailAdapter().send(
        "a@b.com,e@f.com",
        "Hi",
        "body",
        cc="c@d.com",
        bcc="x@y.com",
        html=True,
        from_address="me@corp.com",
        dry_run=False,
    )
    assert out["sent"] is True
    subj, _path, is_html, from_addr, to_j, cc_j, bcc_j = seen["argv"]
    assert (subj, is_html, from_addr) == ("Hi", "1", "me@corp.com")
    assert to_j == f"a@b.com{US}e@f.com"
    assert (cc_j, bcc_j) == ("c@d.com", "x@y.com")


def test_send_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().send("  ", "Hi", "body", dry_run=False)


def test_send_rejects_empty_subject_and_body():
    with pytest.raises(ValueError, match="subject or a body"):
        mail.MailAdapter().send("a@b.com", "", "", dry_run=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail.py -k "send or split_addrs" -v`
Expected: FAIL with `AttributeError: module … has no attribute '_split_addrs'`

- [ ] **Step 3: Add the AppleScript**

In `mail.py`, after `_DELETE_DRAFT`:

```python
# send (#83): the FIRST tool here that dispatches outside this machine — gated by
# MACOS_APPS_ALLOW_SEND at registration, so it does not exist unless the operator opted
# in. `visible:false` + `send` is device-verified (2026-07-25): the "send needs a visible
# compose window" folklore does not hold. Recipient lists arrive as ONE argv item per
# field, US-joined (an email address cannot contain U+001F). Body via tempfile as
# «class utf8». Atomic (#44): delete the partial message on any post-creation error —
# note that Mail may still keep an autosaved Drafts copy, a known Mail behaviour we
# cannot fully suppress, which is exactly why the DRY-RUN path builds nothing at all.
_SEND = """on run argv
  set subj to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  set isHtml to (item 3 of argv) is "1"
  set fromAddr to item 4 of argv
  set toList to item 5 of argv
  set ccList to item 6 of argv
  set bccList to item 7 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set msg to make new outgoing message with properties {visible:false}
    try
      set subject of msg to subj
      if isHtml then
        set html content of msg to bodyText
      else
        set content of msg to bodyText
      end if
      if fromAddr is not "" then set sender of msg to fromAddr
      set AppleScript's text item delimiters to us
      repeat with a in (text items of toList)
        if (a as text) is not "" then
          tell msg to make new to recipient with properties {address:(a as text)}
        end if
      end repeat
      repeat with a in (text items of ccList)
        if (a as text) is not "" then
          tell msg to make new cc recipient with properties {address:(a as text)}
        end if
      end repeat
      repeat with a in (text items of bccList)
        if (a as text) is not "" then
          tell msg to make new bcc recipient with properties {address:(a as text)}
        end if
      end repeat
      set AppleScript's text item delimiters to ""
      send msg
      return "sent"
    on error errMsg
      set AppleScript's text item delimiters to ""
      try
        delete msg
      end try
      error errMsg
    end try
  end tell
  end timeout
end run"""
```

- [ ] **Step 4: Add the adapter code**

Module-level, next to `_parse_draft_records`:

```python
def _split_addrs(value) -> list[str]:
    """Normalize a recipient argument to a list of addresses. Accepts a comma-separated
    string (what a model usually produces) or a list; blanks are dropped. None → []."""
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(a).strip() for a in items if str(a).strip()]
```

On `MailAdapter`, after `delete_draft`:

```python
    def send(
        self,
        to,
        subject: str = "",
        body: str = "",
        cc=None,
        bcc=None,
        html: bool = False,
        from_address: str | None = None,
        dry_run: bool = True,
    ) -> dict:
        """Send a NEW mail — the one path here that leaves this machine.

        ``dry_run=True`` (the default, deliberately inverted from the id-addressed
        deletes) returns the resolved envelope and makes NO call into Mail: a send
        CONSTRUCTS its recipient, so a wrong recipient is the failure that matters, and a
        dry run must not strand an autosaved draft in the user's mailbox.

        ``from_address`` sets the sending account. Omitted, Mail picks its default — which
        is NOT predictable from account order (device-verified), so the preview reports
        "(Mail default account)" rather than a guess. Addresses accept a comma-separated
        string or a list; ``html=True`` sends the body as HTML.
        """
        to_list = _split_addrs(to)
        if not to_list:
            raise ValueError("send_mail needs at least one recipient address (to)")
        if not (subject or "").strip() and not (body or "").strip():
            raise ValueError("send_mail needs a subject or a body (both were empty)")
        cc_list, bcc_list = _split_addrs(cc), _split_addrs(bcc)
        sender = (from_address or "").strip()
        envelope = {
            "to": to_list,
            "cc": cc_list,
            "bcc": bcc_list,
            "from": sender or "(Mail default account)",
            "subject": subject or "",
        }
        if dry_run:
            return {
                "dry_run": True,
                "would_send": {
                    **envelope,
                    "body_chars": len(body or ""),
                    "html": bool(html),
                },
            }
        with body_file(body or "") as path:
            run_osascript(
                _SEND,
                subject or "",
                path,
                "1" if html else "0",
                sender,
                US.join(to_list),
                US.join(cc_list),
                US.join(bcc_list),
            )
        return {"sent": True, **envelope}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k "send or split_addrs" -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Register the tool**

In `server.py`, after `delete_draft`:

```python
@_send_tool("mail")
def send_mail(
    to: str,
    subject: str = "",
    body: str = "",
    cc: str | None = None,
    bcc: str | None = None,
    html: bool = False,
    from_address: str | None = None,
    dry_run: bool = True,
) -> dict:
    """SEND a new mail — this leaves your machine and cannot be recalled.

    `dry_run` DEFAULTS TO TRUE: the first call previews the resolved envelope without
    touching Mail. Pass `dry_run=False` to actually send. Addresses are comma-separated
    (or a list). `from_address` picks the sending account; omitted, Mail uses its default.
    `html=True` sends the body as HTML. Registered ONLY when MACOS_APPS_ALLOW_SEND enables
    the mail adapter. Needs Automation access for Mail.
    """
    return _mail.send(
        to,
        subject,
        body,
        cc=cc,
        bcc=bcc,
        html=html,
        from_address=from_address,
        dry_run=dry_run,
    )
```

- [ ] **Step 7: Classify the tool**

In `tests/test_tool_annotations.py`:

Add to `_DESTRUCTIVE_TOOLS`: `"send_mail"`. Add to `_PERMISSION`: `"send_mail": "Automation",`.

Then make `test_every_write_tool_is_audit_classified` gate-aware — send tools are unregistered in a
default test run, so they must only join `envelope_only` when the gate is on:

```python
    if srv._allow_send("mail"):
        envelope_only |= {"send_mail", "reply_all", "forward_mail"}
```

Add a registration test to `tests/test_tool_annotations.py`:

```python
def test_send_tools_absent_by_default():
    # "Never sends" is the default: with MACOS_APPS_ALLOW_SEND unset, the outbound tools
    # are not registered at all — absent, not erroring.
    live = {t.name for t in _tools()}
    assert not ({"send_mail", "reply_all", "forward_mail"} & live)
```

- [ ] **Step 8: Document in README**

Add a row to the Mail tool table:

```markdown
| `send_mail` | `to`, `subject`, `body`, `cc`, `bcc`, `html`, `from_address`, `dry_run` | **gated** by `MACOS_APPS_ALLOW_SEND`; `dry_run` defaults to `True` |
```

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add macos_apps_mcp/adapters/mail.py macos_apps_mcp/server.py tests/ README.md
git commit -m "feat(mail): #83 send_mail — gated, dry-run-by-default outbound

First tool here that leaves the machine. dry_run defaults True and makes NO
native call: a send constructs its recipient (unlike the id-addressed
deletes), and building an outgoing message can strand an autosaved draft.

from_address lets the caller CHOOSE the sending account — Mail's default is
not predictable from account order (device-verified), so the preview never
guesses it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `reply_all` and `forward_mail` (#83, gated)

**Files:**
- Modify: `macos_apps_mcp/adapters/mail.py`
- Modify: `macos_apps_mcp/server.py`
- Test: `tests/test_mail.py`, `tests/test_tool_annotations.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `_send_tool` (Task 1), `_split_addrs` (Task 4), `_ORIGINAL`, `_build_quote`,
  `sanitize_line`, `_MISSING_VALUE`, `body_file`, `US` (all existing).
- Produces: `MailAdapter.reply_all(message_id, body, include_quote=True, dry_run=True) -> dict`,
  `MailAdapter.forward(message_id, to, body="", dry_run=True) -> dict`, and both tools.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mail.py`:

```python
def test_reply_all_dry_run_touches_nothing(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().reply_all("<orig@x>", "Sounds good")
    assert out == {
        "dry_run": True,
        "would_send": {
            "reply_to": "<orig@x>",
            "reply_all": True,
            "body_chars": 11,
            "include_quote": True,
        },
    }


def test_reply_all_sends_with_quote(monkeypatch):
    seen = {}
    bodies = {}

    def fake(script, *argv):
        seen[script] = argv
        if script is mail._ORIGINAL:
            return f"Boss <boss@corp.com>{US}Tue, 1 Jul 2026{US}Original text"
        return "sent"

    def fake_body_file(text):
        bodies["text"] = text
        return nullcontext("/tmp/fake-body")

    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail, "body_file", fake_body_file)
    out = mail.MailAdapter().reply_all("<orig@x>", "Sounds good", dry_run=False)
    assert out == {"sent": True, "reply_to": "<orig@x>", "reply_all": True}
    assert bodies["text"].startswith("Sounds good")
    assert "> Original text" in bodies["text"]
    assert seen[mail._REPLY_ALL] == ("<orig@x>", "/tmp/fake-body")


def test_reply_all_rejects_empty_body():
    with pytest.raises(ValueError, match="non-empty"):
        mail.MailAdapter().reply_all("<orig@x>", "   ", dry_run=False)


def test_forward_dry_run_reports_recipients(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not call osascript")

    monkeypatch.setattr(mail, "run_osascript", boom)
    out = mail.MailAdapter().forward("<orig@x>", "a@b.com, c@d.com", "FYI")
    assert out["dry_run"] is True
    assert out["would_send"]["to"] == ["a@b.com", "c@d.com"]
    assert out["would_send"]["forwarding"] == "<orig@x>"


def test_forward_sends_via_argv(monkeypatch):
    seen = {}

    def fake(script, *argv):
        seen[script] = argv
        return "sent"

    monkeypatch.setattr(mail, "run_osascript", fake)
    monkeypatch.setattr(mail, "body_file", lambda t: nullcontext("/tmp/fwd-body"))
    out = mail.MailAdapter().forward("<orig@x>", "a@b.com", "FYI", dry_run=False)
    assert out == {"sent": True, "to": ["a@b.com"], "forwarding": "<orig@x>"}
    assert seen[mail._FORWARD] == ("<orig@x>", "/tmp/fwd-body", "a@b.com")


def test_forward_rejects_missing_recipient():
    with pytest.raises(ValueError, match="recipient"):
        mail.MailAdapter().forward("<orig@x>", "", "FYI", dry_run=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mail.py -k "reply_all or forward" -v`
Expected: FAIL with `AttributeError: 'MailAdapter' object has no attribute 'reply_all'`

- [ ] **Step 3: Add the AppleScripts**

In `mail.py`, after `_SEND`:

```python
# reply_all (#83): Mail's NATIVE reply verb with `reply to all yes`, so In-Reply-To /
# References are set by Mail (the only mechanism that threads — make-new-outgoing cannot
# set headers). `opening window no` keeps it headless; device-verified 2026-07-25, returns
# an outgoing message with the Re: subject already applied. The body (reply text + our
# quote, built in Python exactly as `reply` does) is set, then sent. Atomic (#44).
_REPLY_ALL = """on run argv
  set mid to item 1 of argv
  set bodyText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set r to reply (item 1 of matches) opening window no reply to all yes
    try
      set content of r to bodyText
      send r
      return "sent"
    on error errMsg
      try
        delete r
      end try
      error errMsg
    end try
  end tell
  end timeout
end run"""

# forward (#83): Mail's native forward verb (device-verified: returns an outgoing message
# with the Fwd: subject and the original content already in place). Our note is PREPENDED
# — setting `content` outright would discard the forwarded original, which is the whole
# point of a forward. Recipients arrive US-joined in one argv item.
_FORWARD = """on run argv
  set mid to item 1 of argv
  set noteText to (read (POSIX file (item 2 of argv)) as «class utf8»)
  set toList to item 3 of argv
  set us to character id 31
  with timeout of 120 seconds
  tell application "Mail"
    set matches to (messages of inbox whose message id is mid)
    if (count of matches) is 0 then error "no inbox message with that message id"
    set f to forward (item 1 of matches) opening window no
    try
      if noteText is not "" then
        set content of f to noteText & linefeed & linefeed & (content of f)
      end if
      set AppleScript's text item delimiters to us
      repeat with a in (text items of toList)
        if (a as text) is not "" then
          tell f to make new to recipient with properties {address:(a as text)}
        end if
      end repeat
      set AppleScript's text item delimiters to ""
      send f
      return "sent"
    on error errMsg
      set AppleScript's text item delimiters to ""
      try
        delete f
      end try
      error errMsg
    end try
  end tell
  end timeout
end run"""
```

- [ ] **Step 4: Add the adapter methods**

On `MailAdapter`, after `send`:

```python
    def reply_all(
        self,
        message_id: str,
        body: str,
        include_quote: bool = True,
        dry_run: bool = True,
    ) -> dict:
        """Reply-all to an inbox message and SEND it. Mail's native reply verb sets the
        threading headers; ``include_quote`` appends the `On <date>, <sender> wrote:`
        block, built in Python exactly as ``reply`` builds it. ``dry_run=True`` (default)
        makes no call into Mail. The sending account is inherited from the original
        message — the correct identity for a thread."""
        mid = message_id.strip().lstrip("<").rstrip(">")
        if not mid:
            raise ValueError("reply_all needs the original message's id")
        if not body.strip():
            raise ValueError("reply_all needs a non-empty body")
        if dry_run:
            return {
                "dry_run": True,
                "would_send": {
                    "reply_to": message_id.strip(),
                    "reply_all": True,
                    "body_chars": len(body),
                    "include_quote": include_quote,
                },
            }
        full = body
        if include_quote:
            raw = run_osascript(_ORIGINAL, mid)
            if raw.strip() and raw.strip() != _MISSING_VALUE:
                sender, _, rest = raw.partition(US)
                date_str, _, original = rest.partition(US)
                full = body + "\n\n" + _build_quote(
                    sanitize_line(sender), sanitize_line(date_str), original
                )
        with body_file(full) as path:
            run_osascript(_REPLY_ALL, mid, path)
        return {"sent": True, "reply_to": message_id.strip(), "reply_all": True}

    def forward(
        self, message_id: str, to, body: str = "", dry_run: bool = True
    ) -> dict:
        """Forward an inbox message and SEND it. The forwarded original is preserved —
        ``body`` is prepended as a note, never substituted for it. ``dry_run=True``
        (default) makes no call into Mail."""
        mid = message_id.strip().lstrip("<").rstrip(">")
        if not mid:
            raise ValueError("forward needs the original message's id")
        to_list = _split_addrs(to)
        if not to_list:
            raise ValueError("forward needs at least one recipient address (to)")
        if dry_run:
            return {
                "dry_run": True,
                "would_send": {
                    "to": to_list,
                    "forwarding": message_id.strip(),
                    "note_chars": len(body or ""),
                },
            }
        with body_file(body or "") as path:
            run_osascript(_FORWARD, mid, path, US.join(to_list))
        return {"sent": True, "to": to_list, "forwarding": message_id.strip()}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mail.py -k "reply_all or forward" -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Register the tools**

In `server.py`, after `send_mail`:

```python
@_send_tool("mail")
def reply_all(
    message_id: str,
    body: str,
    include_quote: bool = True,
    dry_run: bool = True,
) -> dict:
    """Reply-all to an inbox message and SEND it — this leaves your machine.

    `dry_run` DEFAULTS TO TRUE: preview first, then pass `dry_run=False` to send.
    message_id is the RFC822 id from a mail read; Mail sets the threading headers natively
    and the sending account is inherited from the original. Registered ONLY when
    MACOS_APPS_ALLOW_SEND enables the mail adapter. Needs Automation access for Mail.
    """
    return _mail.reply_all(message_id, body, include_quote, dry_run=dry_run)


@_send_tool("mail")
def forward_mail(
    message_id: str, to: str, body: str = "", dry_run: bool = True
) -> dict:
    """Forward an inbox message and SEND it — this leaves your machine.

    `dry_run` DEFAULTS TO TRUE: preview first, then pass `dry_run=False` to send. `body`
    is prepended as your note; the forwarded original is preserved. `to` is
    comma-separated. Registered ONLY when MACOS_APPS_ALLOW_SEND enables the mail adapter.
    Needs Automation access for Mail.
    """
    return _mail.forward(message_id, to, body, dry_run=dry_run)
```

- [ ] **Step 7: Classify the tools**

In `tests/test_tool_annotations.py`, add `"reply_all"` and `"forward_mail"` to
`_DESTRUCTIVE_TOOLS`, and to `_PERMISSION`:

```python
    "reply_all": "Automation",
    "forward_mail": "Automation",
```

(The `envelope_only` gate-aware line and `test_send_tools_absent_by_default` from Task 4 already
name all three tools.)

- [ ] **Step 8: Document in README**

Add rows to the Mail tool table:

```markdown
| `reply_all` | `message_id`, `body`, `include_quote`, `dry_run` | **gated**; native threading headers |
| `forward_mail` | `message_id`, `to`, `body`, `dry_run` | **gated**; `body` is prepended, original preserved |
```

- [ ] **Step 9: Verify and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add macos_apps_mcp/adapters/mail.py macos_apps_mcp/server.py tests/ README.md
git commit -m "feat(mail): #83 reply_all + forward_mail — gated outbound

Both use Mail's native verbs (device-verified headless), so reply_all keeps
real In-Reply-To/References threading. forward PREPENDS the note instead of
setting content outright, which would discard the forwarded original.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: On-device integration tests + CHANGELOG

**Files:**
- Create: `tests/integration/test_mail_outbound.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_mail_outbound.py`:

```python
"""On-device Mail outbound tests (#82/#83) — NEVER run in CI.

Every send here targets SELF_ADDRESS, the operator's own address. No test in this file
may ever address a third party: a failed assertion is recoverable, a mis-sent mail is not.

Run with:  MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -k outbound
"""

from __future__ import annotations

import os

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration

SELF_ADDRESS = "andrei@lav.ren"
MARKER = "macos-apps-mcp integration"


def test_list_drafts_returns_pointers():
    out = MailAdapter().list_drafts()
    assert isinstance(out, list)
    for p in out:
        assert p.id and p.deeplink.startswith("message://")


def test_dry_run_send_leaves_no_draft_behind():
    # The regression this guards: constructing an outgoing message can strand an
    # autosaved copy in Drafts. A dry run must construct nothing.
    before = {p.id for p in MailAdapter().list_drafts()}
    out = MailAdapter().send(SELF_ADDRESS, f"{MARKER} dry", "body")
    assert out["dry_run"] is True
    assert {p.id for p in MailAdapter().list_drafts()} == before


@pytest.mark.skipif(
    os.environ.get("MACOS_APPS_ALLOW_SEND") is None,
    reason="set MACOS_APPS_ALLOW_SEND=mail to run the real-send test",
)
def test_send_to_self_and_delete_draft_round_trip():
    adapter = MailAdapter()
    subject = f"{MARKER} send"
    out = adapter.send(SELF_ADDRESS, subject, "integration body", dry_run=False)
    assert out == {
        "sent": True,
        "to": [SELF_ADDRESS],
        "cc": [],
        "bcc": [],
        "from": "(Mail default account)",
        "subject": subject,
    }
    # a real send must not leave a draft behind either
    assert not [p for p in adapter.list_drafts() if subject in p.summary]
```

- [ ] **Step 2: Run the read-only integration tests**

Run: `uv run pytest -m integration -k "outbound and not send_to_self" -v`
Expected: PASS (2 tests) — no mail is sent by these.

- [ ] **Step 3: Run the real-send test once, deliberately**

Run: `MACOS_APPS_ALLOW_SEND=mail uv run pytest -m integration -k send_to_self -v`
Expected: PASS, and one mail from you arrives in your own inbox. Delete it afterwards.

- [ ] **Step 4: Confirm the gate actually gates, end to end**

Run: `uv run pytest -m integration -k outbound -v` with `MACOS_APPS_ALLOW_SEND` **unset**
Expected: the real-send test is SKIPPED (not failed), proving the opt-in is required.

- [ ] **Step 5: Update CHANGELOG**

Under a new `## 0.9.0 (unreleased)` heading in `CHANGELOG.md`:

```markdown
### Added
- **Outbound, gated (#104, #83).** `MACOS_APPS_ALLOW_SEND` opts in per adapter
  (`mail`, `mail,messages`, or `1`/`all`); unset — the default — registers no send tools at
  all. `MACOS_APPS_READ_ONLY` always wins. New: `send_mail`, `reply_all`, `forward_mail`,
  each annotated destructive + open-world and defaulting to `dry_run=True`.
- **Drafts lifecycle (#82).** `drafts` lists Mail drafts as pointers; `delete_draft`
  removes one by message-id with `dry_run` preview and audit before-state. Both are
  ungated by `ALLOW_SEND` — listing and deleting your own drafts is not outbound.

### Notes
- `send_draft` was investigated and dropped: Mail's `send` verb applies only to an
  `outgoing message`, never to a message stored in Drafts (`-1708`, device-verified).
```

- [ ] **Step 6: Full verification and commit**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check .
git add tests/integration/test_mail_outbound.py CHANGELOG.md
git commit -m "test(mail): #82/#83 on-device outbound tests + CHANGELOG

Every send targets the operator's own address only. The real-send test is
skipped unless MACOS_APPS_ALLOW_SEND is set, so a bare integration run
cannot send mail.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Post-implementation

- [ ] Opus whole-branch review (`superpowers:requesting-code-review`).
- [ ] File a follow-up issue: `_CREATE_DRAFT`'s #44 rollback (`delete msg` on a post-creation error)
      is subject to the autosave-stranding trap and may leave an orphaned draft. Out of scope here.
- [ ] PR → `develop`, rebase-merge, `--delete-branch`, reset local `develop` to `origin/develop`.
- [ ] Close #104, #82 (with a note that `send_draft` is not implementable), #83.
