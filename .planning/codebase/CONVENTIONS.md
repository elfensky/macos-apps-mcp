# Coding Conventions

**Analysis Date:** 2026-08-28

## Naming Patterns

**Files:**
- Snake case for modules: `mail.py`, `mail_addressing.py`, `test_mail_search.py`
- Test files: `test_<module>.py` for unit tests, `integration/test_<module>.py` for device tests

**Functions:**
- Snake case: `get_pointers()`, `run_osascript()`, `_verify_reminder()`
- Private functions start with single underscore: `_fake_reminder()`, `_resolve_list()`
- Internal helpers (never exported): `_require_full_access()`

**Classes & Types:**
- PascalCase: `MailAdapter`, `Pointer`, `ReminderData`, `AccessDenied`
- Protocol types (runtime checkable): `PointerSource`, `Snapshotter`
- Frozen dataclasses for contracts: `Pointer`, `ReminderData`, `CalendarEventData`

**Variables & Constants:**
- Snake case for local/module-level: `_WRITE_TOOLS`, `_SEND_ANNOTATIONS`, `_SEAM`
- UPPER_CASE for truly immutable config constants: `BODY_MAX`, `SUMMARY_MAX`, `US`, `RS` (wire framing separators)
- Boolean functions return `is_*()` or `_allow_*()`

**Module-level Singletons:**
- Named adapters registered at module load: `_reminders`, `_calendar`, `_mail` in `server.py`
- Used by decorators at registration time (set BEFORE launching server)

## Code Style

**Formatting:**
- Tool: `ruff` (both linter and formatter)
- Line length: 88 characters
- Configured in `pyproject.toml` with `[tool.ruff]` section

**Linting Rules:**
- Active rule sets: `E` (errors), `F` (pyflakes), `I` (isort imports), `UP` (modernize), `B` (bugbear), `SIM` (simplify)
- Target: Python 3.11+ (`target-version = "py311"`)
- Exception: `docs/` directory excluded (frozen historical content)

**Type Hints:**
- Use full type hints in function signatures
- No mypy enforcement (Protocol seam keeps tool layer testable without it)
- Use `Protocol` + `runtime_checkable` for structural typing: `isinstance(fake, PointerSource)` works without inheritance

**From Future Imports:**
- Always include `from __future__ import annotations` at top of modules (enables forward references)

## Import Organization

**Order:**
1. `from __future__ import annotations`
2. Standard library (e.g., `import os`, `import sqlite3`)
3. Third-party imports (e.g., `from fastmcp import FastMCP`, `import EventKit`)
4. Relative imports from this package (e.g., `from . import deploy`, `from .contracts import Pointer`)

**Path Aliases:**
- None configured (flat package layout)
- Relative imports preferred: `from .. import runtime` (allows `monkeypatch.setattr(runtime, ...)` in tests)

**Qualified Imports in Native Modules:**
- Mail adapters MUST use qualified imports: `from .. import runtime` then call `runtime.run_osascript()`, NOT `from ..runtime import run_osascript` (#176)
- Test verification: `tests/test_native_seam.py` ensures all mail modules follow this rule
- Reason: Single monkeypatch point per test (`runtime.run_osascript` sealing)

## Error Handling

**Typed Error Taxonomy:**
- Base class: `NativeError` (all raised, never caught silently)
- Located in `macos_apps_mcp/errors.py`
- Every subclass has a unique `kind` attribute and agent-directed message:
  - `AccessDenied` - TCC grant missing (names the Settings pane)
  - `AutomationDenied` - osascript blocked
  - `AppNotRunning` - target app not available
  - `NativeTimeout` - call exceeded deadline
  - `SchemaDrift` - native output shape changed (OS/app update)
  - `VerificationFailed` - write didn't persist as requested (#49)
  - `WriteRefused` - store rejected the save (read-only container, iCloud reverted)
  - `SpanRequired` - recurring event edit needs explicit span
  - `RecurrenceRequired` - recurring reminder edit needs recurrence re-send
  - `BatchTooLarge` - bulk operation exceeded safety cap (#54)
  - `AmbiguousTarget` - name matched multiple containers (#55)
  - `FullDiskAccessDenied` - sqlite store unopenable
  - `OutputOverflow` - result exceeded size cap

**Convention:**
- Raise early with typed errors, never let failures be silent
- `str(e)` IS the agent-facing remediation (e.g., "Grant it in System Settings → Privacy & Security")
- Server.py's `@_guard()` decorator converts `NativeError` + `ValueError` to MCP `ToolError` results
- Never mask errors with empty results `[]` or fabricated values

**Value Errors:**
- Boundary validation (bad datetime, unknown id, ambiguous name) raises `ValueError`
- Message must be agent-directed (e.g., "expected ISO-8601 datetime; got...")
- Lives in contracts.py/text.py parsers, caught by `@_guard()` at tool boundary

## Logging

**Framework:**
- Use `logging` module (not `print()`)
- Logger created per module: `logger = logging.getLogger(__name__)`
- Never left in production code without explicit configure (tests may use `caplog`)

**Levels:**
- `info()`: Major operations (adapter init, command dispatch)
- `debug()`: Internal flow (parsing, matching)
- `warning()`: Recoverable issues (schema drift fallback, slow queries)
- `error()`: Typed failures (logged before raising NativeError)

**No Debug Spam:**
- Avoid logging every parse iteration, every field coercion
- Use logging for state changes visible in doctor output

## Comments & Docstrings

**Module Docstrings:**
- Describe module purpose and design decisions
- Reference GitHub issues (#123) where design was debated
- Show the problem the module solves (e.g., "Pure by design: nothing here touches EventKit/PyObjC/Foundation")

**Function Docstrings:**
- Describe WHAT the function does and WHY (not HOW)
- Include return type and behavior
- Reference contracts/preconditions (e.g., "An aware value is *converted* to local before...")

**Tool Docstrings (Required):**
- MUST state which macOS permission is required (or "None" for meta tools)
- Permission keywords: "EventKit", "Automation", "Full Disk Access", "Shortcuts CLI"
- Used by `tests/test_tool_annotations.py` to verify tool registration
- Format: Start sentence with permission name in docstring, e.g., "Requires **Automation** to control..."
- Tuple permissions: "Requires **Full Disk Access** and **Automation**" (both are mandatory)
- Example from `test_tool_annotations.py`: Tool `mail_search` needs `("Full Disk Access", "Automation")`, so docstring must name both

**Inline Comments:**
- Use for non-obvious logic, algorithm choice, or workaround reason
- Avoid: Restating what the code obviously does
- Reference issues: `# #123: a Mail write can silently revert via iCloud`

**Type Comments:**
- Rare (use type hints instead)
- Only when annotation syntax doesn't fit: `# type: ignore[attr-defined]`

## Function Design

**Size:**
- Aim for ~25 lines typical, up to 50 for helpers
- Longer functions: Split into named sub-functions within the module
- Adapters: Thin public methods delegate to `_private_helpers()`

**Parameters:**
- Use positional args for required values
- Use keyword-only args (after `*`) for options
- Type hint everything
- Example: `def create(self, data: ReminderData, *, dry_run: bool = False) -> Pointer:`

**Return Values:**
- Single primary return: `Pointer`, `dict`, `list[...]`
- Errors: Raise typed exception, never return `None` for failure
- Tool returns: All wrapped in `@_guard()` to convert errors to `ToolError`

**Dry Run Pattern:**
- Adapters own `dry_run` parameter
- Dry-run path must make **NO native call at all** (conftest's fail-close guard validates this)
- Dry-run returns: deletion shows `{"dry_run": True, "would_delete": <Pointer>}`, creation shows `{"created": id}`

## Module Design

**Exports (Public API):**
- All public functions and classes at module top level
- Adapters: One per app under `macos_apps_mcp/adapters/`
- Tools: Defined at module level in `server.py` with decorator
- Contracts: Data classes + Protocol types in `contracts.py`

**Barrel Files:**
- `macos_apps_mcp/__init__.py`: Exports `main` entry point only
- No re-export of adapters/helpers (keep surface small)

**Adapter Protocol Contracts:**
- Reads implement `PointerSource`: `get_pointers(query: str) -> list[Pointer]`
- Enumeration reads: Per-adapter typed methods (e.g., `get_calendars()`, `get_lists()`)
- Writes: Per-adapter typed methods (e.g., `create_reminder(ReminderData)`, `create_event(CalendarEventData)`)
- Reason: Typed per-adapter prevents stringly-typed rot, keeps types correct

**Snapshotter Registration:**
- Every id-addressed write tool must register its snapshot function
- Declaration: `@_write_tool(snapshot=_mail.snapshot)` in `server.py`
- Snapshot function: `snapshot(id: str) -> Pointer | None` (before-state for audit)
- Verification: `test_tool_annotations.py` ensures all write tools declare snapshotters

**Decorator Tiers (#57, #130):**
- `@_read_tool`: Read-only tools, annotated `readOnlyHint: true`
- `@_additive_tool`: Write that only ADDS new items (create/open), annotated `destructiveHint: false`
- `@_write_tool`: Modifies/overwrites/deletes existing state, annotated `destructiveHint: true`
- `@_send_tool("<adapter>")`: Outbound (leaves this machine), registered only when `MACOS_APPS_ALLOW_SEND` enables that adapter
- All tools wrapped by `@_guard()` to convert native errors to results

## Text Hygiene

**Output Sanitization (#52):**
- All free-text fields (subject, body, note, contact name) pass through:
  - `clean_summary()`: Strip control chars, bound to SUMMARY_MAX (256)
  - `clean_body()`: Strip control chars, bound to BODY_MAX (16KB)
  - `sanitize_line()`: Strip control + whitespace, for single-line fields
  - `sanitize_block()`: Strip control chars in multi-line body
- Reason: Pathological input (embedded nulls, control chars) corrupts wire protocol or blows context window

**Verification Normalization (#49):**
- `norm_text()`: NFC-normalized, LF-normalized for write verification
- Used by `verify_persisted()` to diff expected vs actual
- Reason: iCloud can revert writes, Mail can drop fields; must catch before returning id to vault

**Matching Folding (#64):**
- `fold_text()`: Case-insensitive, diacritic-insensitive, smart-punct-insensitive search
- Used for name/title matching (resolve_list, resolve_container)
- Reason: User types "Café" but Mail stores "Cafe"; `fold_text()` makes both match

**Wire Framing (#68):**
- AppleScript separators: `US = "\x1f"` (unit sep), `RS = "\x1e"` (record sep)
- All free-text fields stripped FIRST: `stripFraming` AppleScript handler (prepended to every template)
- Python splitter: `split_framed()` → `list[list[str]]` records
- One home for this protocol: `text.py` (constants, handlers, splitter)
- Never hardcode `\x1f`/`\x1e` in adapters

## Dataclass & Frozen Patterns

**Pointer (Immutable Citation Contract):**
- `@dataclass(frozen=True)` prevents accidental mutation
- Attributes: `id`, `summary`, `deeplink`, optional `folder`
- Serialized via `as_dict()` for MCP wire
- Reason: Vault writes depend on id correctness; frozen enforces it

**Typed Write Payloads:**
- `ReminderData(title, due=None, list_name=None, priority=0, start=None, recurrence=None)`
- `CalendarEventData(title, start, end, calendar=None, location=None, all_day=False, recurrence=None)`
- Validates invariants in `__post_init__()`: reminds need due for recurrence, priority bounds
- Reason: Type safety + invariant checks at boundary, before adapter sees bad data

**Parse Result Envelopes:**
- `read_result()`: Wraps list of Pointers with optional `truncated`, `plane`, `coverage` flags
- `deletion_result()`: Shows dry-run preview or confirmation id
- Reason: Distinguishes "nothing found" from "incomplete read under cap"

## Constants & Magic Numbers

**Configuration Constants:**
- `BODY_MAX = 16 * 1024` - max output body (mail_bodies, note_bodies)
- `SUMMARY_MAX = 256` - max summary string
- `_ACCESS_TIMEOUT = 120.0` - seconds before TCC prompt/EventKit hung
- `MAX_MAILS = 100` - default query cap
- `MAX_THREADS = 10` - thread-limiting for bulk operations

**Wire Separators (Single Home in text.py):**
- `US = "\x1f"` - field separator in AppleScript templates
- `RS = "\x1e"` - record separator in AppleScript templates
- `STRIP_FRAMING` - AppleScript handler (prepended to every template using these)
- `READ_BODY` - AppleScript handler for -39 "End of file" on zero-byte reads

**Env Vars (Checked at Registration Time):**
- `MACOS_APPS_READ_ONLY` - Set to 1 before launch to skip write tool registration
- `MACOS_APPS_ALLOW_SEND` - Set to "mail" or "all" before launch to enable outbound tools
- Both checked by `_read_only()` and `_allow_send(adapter)` at module import (registration)

## Design Patterns

**Thin Dispatch Pattern:**
- Tools in `server.py` are one-line delegations: `return _reminders.create(data)`
- Adapters own business logic and native calls
- Error handling via `@_guard()` wrapper (tool layer doesn't know about typed errors)

**Protocol Contracts (Structural Typing):**
- No ABC or inheritance
- Fakes satisfy contract by duck typing: `isinstance(fake, PointerSource)` works
- Reason: Tests can use plain `SimpleNamespace` instead of full mock objects

**Monkeypatch Sealing (conftest):**
- Session scope: `_isolated_state()` moves XDG_STATE_HOME, patches `deploy._ALLOW_SEND_FILE`
- Per-test scope: `_no_real_osascript()` replaces `runtime.run_osascript` with refusal
- Per-test scope: `_reset_account_map_globals()` resets mail_addressing cache before each test
- Reason: Fail-closed on native calls, hermetic state, no leaks to next test

**Three-Tier Capability Gating (#57, #130):**
- Read tier: Always registered
- Write tier: Skipped if `MACOS_APPS_READ_ONLY=1`
- Send tier: Registered only if `MACOS_APPS_ALLOW_SEND` names adapter
- Tool absence (not erroring) signals gate

---

*Convention analysis: 2026-08-28*
