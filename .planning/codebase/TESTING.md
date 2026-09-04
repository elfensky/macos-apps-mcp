# Testing Patterns

**Analysis Date:** 2026-08-28

## Test Framework

**Runner:**
- pytest 8.x—10.x
- Config: `pyproject.toml` `[pytest.ini_options]`
- Default: Runs unit tests only (`-m 'not integration'`)
- Coverage: pytest-cov 6.x—8.x

**Assertion Library:**
- Built-in `assert` statements
- pytest comparison messages for clarity
- `pytest.raises(ExceptionType, match="pattern")` for exception testing

**Run Commands:**
```bash
uv run pytest                   # Run unit tests (integration skipped by default)
uv run pytest -m integration    # Run device tests manually, NEVER in CI
uv run pytest tests/test_*.py   # Run specific test file
uv run pytest -v --tb=short     # Verbose output, short tracebacks
uv run pytest --co              # List all tests without running
uv run pytest --cov macos_apps_mcp --cov-report=html  # Coverage report
```

## Test File Organization

**Location:**
- Unit tests: `tests/test_<module>.py` (parallel to source structure)
- Integration tests: `tests/integration/test_<module>.py` (device tests)

**Naming:**
- Files: `test_<what>.py` (e.g., `test_reminders.py`, `test_mail_search.py`)
- Test functions: `test_<behavior>()` (e.g., `test_summary_with_due()`)
- Helper functions: `_<role>()` (e.g., `_fake_reminder()`, `_fake_store()`)

**Directory Structure:**
```
tests/
├── __init__.py                          # empty, marks package
├── _fakes.py                            # shared fake objects (SimpleNamespace structs)
├── conftest.py                          # session/module-scoped fixtures (isolation guards)
├── test_contracts.py                    # adapter contract + datetime parsing
├── test_calendar.py                     # CalendarAdapter unit tests
├── test_mail.py, test_mail_search.py    # Mail suite (split by concern)
├── test_reminders.py                    # RemindersAdapter unit tests
├── test_server.py                       # Server dispatch + MCP integration
├── test_text.py                         # text.py helpers (pure)
├── test_runtime.py                      # runtime.py helpers (pure)
├── test_tool_annotations.py             # Tool registration + permission audit
├── test_native_seam.py                  # Mail module import audit (#176)
├── test_native_seam.py                  # AppleScript timeout testing
├── integration/
│   ├── test_mail_outbound.py            # Send/reply/forward on real Mail
│   └── test_music_integration.py        # Music adapter on real macOS
└── ...
```

## Test Structure

**Suite Organization:**
```python
"""Module docstring explaining what this test suite covers and why."""

from __future__ import annotations

import pytest
from macos_apps_mcp.adapters.reminders import (
    _reminder_pointer,
    _resolve_list,
)
from macos_apps_mcp.contracts import Pointer
from tests._fakes import fake_rule


def _fake_reminder(title, ident, due=None):
    """Helper producing a test fixture — plain SimpleNamespace, no inheritance."""
    return SimpleNamespace(title=lambda: title, ...)


def test_summary_with_due():
    """Test name describes the scenario being tested."""
    item = _fake_reminder("Call dentist", "R-1", due=(2026, 6, 23))
    assert _reminder_summary(item) == "Call dentist — due 2026-06-23"


def test_resolve_named_list():
    """Each test is independent; fakes are created fresh."""
    s = _fake_store(["Work", "Home"])
    assert _resolve_list(s, "Home").title() == "Home"
```

**Patterns:**

1. **Docstring per test:** Describes scenario (not just restating code)
2. **Fresh fakes:** Each test creates its own SimpleNamespace fixtures (no shared state)
3. **Assertion-per-line:** One `assert` per key fact (multiple assertions per test is ok)
4. **Test names describe scenarios:** `test_summary_with_due()` not `test_reminder()`

## Mocking

**Framework:**
- pytest's built-in `monkeypatch` fixture (function-scoped)
- pytest.MonkeyPatch (session-scoped, used in conftest for sealing)
- `SimpleNamespace` fakes (no mocking library, no mock.Mock)

**Qualified Import Pattern (#176):**
```python
# CORRECT: Imports module, not the function
from .. import runtime
from .. import deploy

# In test, monkeypatch the module's attribute
monkeypatch.setattr(runtime, "run_osascript", fake_osascript)
monkeypatch.setattr(deploy, "_ALLOW_SEND_FILE", tmp_path / "allow_send")
```

```python
# WRONG: Imports function directly into namespace
from ..runtime import run_osascript  # DON'T DO THIS
# Reason: A test that patches a different module won't affect this import (#176)
```

**Why:** Mail adapters must all reach ONE seam point (`runtime.run_osascript`) so one monkeypatch applies everywhere. Qualified imports enforce this.

**Protocol Fakes (Structural Typing):**
```python
class FakeReminders:
    """Implements PointerSource structurally—no inheritance."""
    
    def get_pointers(self, query: str) -> list[Pointer]:
        return [
            Pointer(
                id="x-1",
                summary=f"reminder ~ {query}",
                deeplink="x-apple-reminderkit://x-1",
            )
        ]


def test_fake_satisfies_pointersource():
    # No inheritance, just duck typing—Protocol + runtime_checkable handles it
    fake = FakeReminders()
    assert isinstance(fake, PointerSource)
    ptrs = fake.get_pointers("dentist")
    assert ptrs[0].id == "x-1"
```

**SimpleNamespace for EventKit Fakes:**
```python
# Instead of: class FakeRule(EKRecurrenceRule): ...
# Use: SimpleNamespace with lambda properties
def fake_rule(freq=0, interval=1, count=None):
    end = None if count is None else SimpleNamespace(occurrenceCount=lambda: count)
    return SimpleNamespace(
        frequency=lambda: freq,
        interval=lambda: interval,
        recurrenceEnd=lambda: end,
    )


def test_recurrence_from_rrule():
    r = fake_rule(freq=1, interval=2)  # Weekly, every 2 weeks
    assert r.frequency() == 1
```

**Reason:** SimpleNamespace is lightweight, no boilerplate, and isinstance() checks work via Protocol + runtime_checkable.

**What to Mock:**
- Native calls: osascript, EventKit (wrap in `run_native()`)
- Adapter methods (return predictable test Pointers)
- File I/O (sqlite paths via monkeypatch)
- Environment variables (via monkeypatch)

**What NOT to Mock:**
- Contract helpers (parse_datetime, parse_recurrence) - test with real values
- Error constructors - test that they raise correctly
- Text hygiene (fold_text, norm_text) - pure functions, test exhaustively
- Datetime math (to_nsdate, from_nsdate) - roundtrip with real values

## Fixtures and Factories

**Test Data (Shared in _fakes.py):**
```python
# _fakes.py — shared across all adapter tests
def fake_rule(freq=0, interval=1, count=None):
    """Minimal EKRecurrenceRule stand-in."""
    end = None if count is None else SimpleNamespace(occurrenceCount=lambda: count)
    return SimpleNamespace(
        frequency=lambda: freq,
        interval=lambda: interval,
        recurrenceEnd=lambda: end,
    )


# In test_reminders.py
from tests._fakes import fake_rule


def _fake_reminder(title, ident, due=None):
    """Test-local helper (not in _fakes) — used only here."""
    return SimpleNamespace(
        title=lambda: title,
        calendarItemIdentifier=lambda: ident,
        dueDateComponents=lambda: ...,
    )
```

**Fixture Scopes:**

**Session-Scoped (conftest.py—one per run):**
```python
@pytest.fixture(autouse=True, scope="session")
def _isolated_state(tmp_path_factory):
    """Isolation guard: Repoint XDG_STATE_HOME and deploy._ALLOW_SEND_FILE.

    Without this, a test run would read/write:
    - Audit log to the developer's real ~/.local/share/
    - The launchd daemon's allow_send toggle to ~/
    """
    state_home = tmp_path_factory.mktemp("xdg-state-home")
    mp = (
        pytest.MonkeyPatch()
    )  # Session scope, so pytest.MonkeyPatch (not monkeypatch fixture)
    mp.setenv("XDG_STATE_HOME", str(state_home))
    mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")
    yield state_home
    mp.undo()
```

**Per-Test Autouse (conftest.py—before every test):**
```python
@pytest.fixture(autouse=True)
def _no_real_osascript(request, monkeypatch):
    """Fail CLOSED on native seam: unit tests that forget to fake osascript raise.
    
    Integration tests marked @pytest.mark.integration are exempt.
    """
    if "integration" in request.keywords:
        return
    
    def _refuse(*_args, **_kwargs):
        raise AssertionError(
            "a unit test reached run_osascript — fake it with "
            "monkeypatch.setattr(runtime, 'run_osascript', ...)"
        )
    
    monkeypatch.setattr(runtime, "run_osascript", _refuse)


@pytest.fixture(autouse=True)
def _reset_account_map_globals(monkeypatch):
    """Reset mail_addressing cache globals before every test.
    
    Two globals (_ACCOUNT_MAP_CACHE, _ACCOUNT_MAP_FAILURE_AT) are a cache pair.
    If only the cache is reset, a stale failure timestamp lingers and a later test's
    monkeypatched cache is silently wiped when its TTL expires. Reset both.
    """
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_FAILURE_AT", None)
```

**SQL Fixture (test_mail_search.py):**
```python
def _fake_envelope(path):
    """Create minimal Envelope Index sqlite with test data.
    
    Deliberately includes duplicate shapes found on real Macs:
    - <abc@ex.com> in INBOX and Archive (cross-folder duplicate)
    - <dup@ex.com> twice in SAME folder (migration copy)
    """
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE messages(ROWID INTEGER PRIMARY KEY, ...);
        INSERT INTO subjects VALUES (1,'Invoice 42'), (2,'Re: Invoice 42'), ...;
        INSERT INTO messages VALUES (10,1,1,1,1,1700000000,1700000000,0,0,0,7), ...;
    """)
    c.commit()
    c.close()


def test_search_returns_pointers_from_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "Envelope Index"
    _fake_envelope(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    out = MailAdapter().search(subject="Invoice")["results"]
    # Now search hits the test sqlite, not the real envelope index
    assert len([p for p in out if p["id"] == "<abc@ex.com>"]) == 1
```

**Location:**
- Shared fakes: `tests/_fakes.py`
- Test-local helpers (used by one test only): Top of test file as `_<name>()`
- Session fixtures: `tests/conftest.py` with `scope="session"` and `autouse=True`
- Per-test fixtures: `tests/conftest.py` with `autouse=True` (function scope default)

## Coverage

**Requirements:**
- No enforced coverage target
- Coverage measured by `pytest-cov`
- View coverage report: `uv run pytest --cov=macos_apps_mcp --cov-report=html`

**Strategy:**
- Unit tests: All adapters, contracts, helpers
- Integration tests: Send, reply, forward (device-verified per mail-applescript-facts.md)
- Pure modules (text.py, contracts.py parsing): 100% coverage expected
- Runtime helpers: Tested with fakes (no EventKit in unit tests)

## Test Types

**Unit Tests:**
- Scope: Single adapter or helper function
- Mocking: Fakes at adapter boundary (Protocol contracts)
- No EventKit, no osascript spawning
- Run: `uv run pytest`
- Default: `pyproject.toml` excludes integration

**Integration Tests:**
- Scope: Real macOS, EventKit, osascript, Mail.app
- Marking: `@pytest.mark.integration`
- Run manually: `uv run pytest -m integration`
- Never run in CI

**Integration Test Discipline:**
- Mail sends: Send to `andrei@lav.ren` ONLY
- Wait for autosave: 20+ seconds before checking Drafts (Mail autosaves ~10–15s asynchronously)
- Verify via device: Assert the resulting message body, attachment count, etc. (not just return value)
- Track passes: Watching for silent test deletions (`grep -c "^def test_"` before/after)
- Example from mail-applescript-facts.md:
  ```python
  # WRONG: Just checking return value
  result = send_mail(...)
  assert result["sent"] is True

  # CORRECT: Verify the message actually arrived
  result = send_mail(...)
  assert result["sent"] is True
  import time

  time.sleep(20)  # Wait for autosave
  # Then manually check Outbox/Sent in Mail.app that the message is there
  ```

## Common Patterns

**Async Testing (via asyncio):**
```python
import asyncio


def test_server_lists_tools():
    """Integration with FastMCP Client — must be async-wrapped."""

    async def _run():
        async with Client(srv.mcp) as c:
            return await c.list_tools()

    tools = asyncio.run(_run())
    assert any(t.name == "reminders" for t in tools)
```

**Error Testing:**
```python
def test_recurrence_rejects_count_and_until_together():
    """ValueError raised when invariant violated."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        Recurrence(frequency="daily", count=5, until=datetime(2026, 12, 31))


def test_require_full_access_raises_on_denied():
    """Native error raised with agent-directed message."""
    with pytest.raises(AccessDenied, match="System Settings"):
        _require_full_access(2)  # EKAuthorizationStatusDenied
```

**Parametrized Testing:**
```python
@pytest.mark.parametrize(
    "status",
    [0, 1, 2, 4],  # notDetermined, restricted, denied, writeOnly
)
def test_require_full_access_raises_on_anything_else(status):
    with pytest.raises(AccessDenied):
        _require_full_access(status)
```

**Monkeypatch Environ & Restore:**
```python
def test_parse_datetime_on_dst_day(monkeypatch):
    """Pin timezone for determinism — test runs on any machine."""
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        aware = "2026-11-01T05:30:00+00:00"  # Fall-back fold UTC instant
        assert (
            parse_datetime(aware).timestamp()
            == datetime.fromisoformat(aware).timestamp()
        )
    finally:
        monkeypatch.undo()
        time.tzset()
```

**Roundtrip Testing:**
```python
def test_nsdate_roundtrip():
    """Pure conversion is lossless to 1-second precision."""
    dt = datetime(2026, 6, 23, 9, 30, 0)
    ns = to_nsdate(dt)
    back = from_nsdate(ns)
    assert abs((back - dt).total_seconds()) < 1
```

**Registration Audit (test_tool_annotations.py):**
```python
def test_every_tool_is_annotated_from_read_write_seam():
    """Every registered tool must have readOnlyHint + destructiveHint."""
    for t in _tools():
        a = t.annotations
        assert a is not None, f"{t.name} has no annotations"
        assert isinstance(a.readOnlyHint, bool), f"{t.name} readOnlyHint not set"
        expected_readonly = t.name not in _WRITE_TOOLS
        assert a.readOnlyHint is expected_readonly, ...
```

**Mail Write Verification:**
All Mail writes MUST be device-verified. Example pattern (not run in CI):
```python
@pytest.mark.integration
def test_forward_mail_preserves_attachments():
    """Forward must NOT destroy attachments (device-verified issue #162)."""
    # 1. Get a message with attachments
    drafts = drafts()
    
    # 2. Forward it
    fwd = forward_mail(message_id=drafts[0].id)
    assert fwd["created"] is not None
    
    # 3. Wait for autosave
    time.sleep(20)
    
    # 4. VERIFY THE ACTUAL MESSAGE IN MAIL.APP
    # - Open Mail → Drafts
    # - Find the forward (check subject)
    # - Verify it has all original attachments
    # Do not proceed without this step (reading code didn't catch #162's attachment loss)
```

## Dry-Run Pattern

**Requirement:**
- Dry-run paths make NO native calls at all (conftest's fail-close guard validates)
- Example: `create_reminder(data, dry_run=True)` returns a pointer preview WITHOUT calling EventKit

**Implementation:**
```python
def create_reminder(self, data: ReminderData, *, dry_run: bool = False) -> Pointer:
    if dry_run:
        # Build a PREVIEW pointer—no native call, no store write
        return Pointer(
            id="<preview-id>",
            summary=data.title,
            deeplink="x-apple-reminderkit://preview",
        )
    # Real create: call run_native(store), save to EventKit, verify
    ...
```

**Testing Dry-Run:**
```python
def test_dry_run_creates_no_entries(monkeypatch):
    """Dry-run doesn't call native seam."""
    # This test verifies no osascript was spawned (conftest's autouse guard)
    adapter = MailAdapter()
    result = adapter.create_draft(..., dry_run=True)
    assert result.id.startswith("<")  # Preview id, not a real Mail message id
```

## Audit & Snapshots

**Snapshot Registration (#67):**
Every id-addressed write tool must register a snapshot function:

```python
# In server.py
@_write_tool(snapshot=_mail.snapshot)  # <-- snapshot parameter
def send_mail(...):
    return _mail.send(...)
```

**Snapshot Function Signature:**
```python
def snapshot(ident: str) -> Pointer | None:
    """Return the before-state of an item, or None if not found."""
    # Used by AuditMiddleware to log before-state
    # mail.snapshot(id) -> find the message in index, return Pointer or None
    return self.get_pointers(f"message_id:{ident}")
```

**Test Verification (test_tool_annotations.py):**
```python
def test_every_write_tool_is_audit_classified():
    """All write tools with ids must declare snapshot functions."""
    # Reads directly from server.py AST to ensure no hand-maintained list
    # (which would drift): derives which tools call adapters, matches against
    # _SNAPSHOT_SOURCES dict populated by @_write_tool(snapshot=...) decorators
    ...
```

---

*Testing analysis: 2026-08-28*
