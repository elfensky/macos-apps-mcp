# Phase 1: Gate — Land the Spiked Architecture Cuts - Pattern Map

**Mapped:** 2026-09-25
**Files analyzed:** 26 (7 new, 19 modified)
**Analogs found:** 26 / 26 (all from current `develop`; spike shapes cited only as secondary
recipes, per CONTEXT.md's "never merge a spike body" rule)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog (current `develop`) | Match Quality |
|---|---|---|---|---|
| `macos_apps_mcp/eventkit.py` (new, card 7) | service (native door) | event-driven (EventKit callbacks) | `macos_apps_mcp/runtime.py` (the functions being extracted, in place) | exact — same file, split not rewrite |
| `macos_apps_mcp/tiers.py` (new, card 5) | config/policy | request-response (pure predicate) | `macos_apps_mcp/server.py:61-104` (`_read_only`, `_allow_send`) | exact — literal function bodies move |
| `macos_apps_mcp/notices.py` (new, card 5) | middleware | request-response | `macos_apps_mcp/audit.py:231-283` (`AuditMiddleware`) | role-match — same FastMCP `Middleware` base, same server.py wiring point |
| `macos_apps_mcp/registry.py` (new, card 2) | service (registry) | CRUD (in-memory record store) | `macos_apps_mcp/server.py:149-230` (`_WRITE_TOOLS`/`_SNAPSHOT_SOURCES`/`_read_tool`/`_write_tool`/`_additive_tool`) | exact — same decorators, one record instead of five sets |
| `tests/envelope.py` (new, card 3) | test fixture | file-I/O (sqlite fixture) | `tests/test_mail_search.py:29-80` (`_fake_envelope`) | exact — promoted, not rewritten |
| `tests/test_registry.py` (new, card 2) | test | CRUD | `tests/test_tool_annotations.py` | role-match — both assert over the tool-registration surface |
| `tests/test_eventkit.py` (new, card 7) | test | event-driven | `tests/test_runtime.py` (the EventKit-touching cases being carved out) | exact — split test file mirrors split source file |
| `tests/test_timeout_tripwire.py` (new, card 9/10) | test | batch | `tests/test_native_seam.py` (an `ast`-based static tripwire over adapter source) | role-match — same static-analysis test shape |
| `macos_apps_mcp/runtime.py` (trim, card 7) | service (native door) | request-response | itself (pre-split) | exact |
| `macos_apps_mcp/server.py` (cards 2, 5, 7) | controller (tool dispatch) | request-response | itself (pre-cards) | exact |
| `macos_apps_mcp/doctor.py` (cards 5, 7) | controller (diagnostics) | request-response | itself (pre-cards) | exact |
| `macos_apps_mcp/audit.py` (card 2/6) | service (audit trail) | event-driven | itself (`_audit_op`, `AuditMiddleware`) | exact |
| `macos_apps_mcp/adapters/mail_recover.py` (card 4) | service (recoverable plane) | CRUD | itself (`check_batch`, `preview`, `recoverable`) | exact |
| `macos_apps_mcp/adapters/mail.py` (cards 4, 9) | adapter | CRUD | itself (`dedupe_batch`, `_DEDUPE`) | exact |
| `macos_apps_mcp/adapters/mail_index.py` (card 3) | adapter (sqlite read plane) | CRUD (read) | itself (`HEADER_FINGERPRINT`, `query_sent_triage`/`query_duplicate_rows`) | exact |
| `macos_apps_mcp/adapters/notes.py` (cards 1, D-02) | adapter | request-response | itself (`delete`, `update`, import block) | exact |
| `macos_apps_mcp/adapters/shortcuts.py` (card 1) | adapter | request-response | itself (import block) | exact |
| `macos_apps_mcp/adapters/calendar.py` (cards 1, 7, D-01) | adapter | request-response | itself (`delete_event`, import block) | exact |
| `macos_apps_mcp/adapters/reminders.py` (card 7) | adapter | request-response | itself (import block) | exact |
| `macos_apps_mcp/adapters/contacts.py` (card 1) | adapter | request-response | `macos_apps_mcp/adapters/mail.py:73` (`from .. import runtime`) | role-match — mail.py is the ALREADY-fixed #176 exemplar |
| `macos_apps_mcp/adapters/photos.py` (card 1) | adapter | request-response | `macos_apps_mcp/adapters/mail.py:73` | role-match |
| `macos_apps_mcp/adapters/safari.py` (card 1) | adapter | request-response | `macos_apps_mcp/adapters/mail.py:73` | role-match |
| `macos_apps_mcp/adapters/messages.py` (card 1) | adapter | request-response | `macos_apps_mcp/adapters/mail.py:73` | role-match |
| `macos_apps_mcp/adapters/music.py` (card 1) | adapter | request-response | `macos_apps_mcp/adapters/mail.py:73` | role-match |
| `tests/conftest.py` (card 1, 3) | test fixture | event-driven (autouse guard) | itself (`_no_real_osascript`) | exact |
| `tests/test_native_seam.py` (card 1) | test | batch (static AST check) | itself | exact |

## Pattern Assignments

### `macos_apps_mcp/eventkit.py` (new — card 7)

**Analog:** `macos_apps_mcp/runtime.py` (the source of every moved function — copy bodies
from current `develop`, never from `spike/arch-review-7-runtime-split@5db5fc5`)

**What moves, verified against current develop's import blocks** (`calendar.py:23-33`,
`reminders.py:21-32`): `store`, `container_id`, `to_nsdate`, `epoch_nsdate`, `from_nsdate`,
`due_components`, `to_recurrence_rule`, `recurrence_signature`,
`persisted_recurrence_signature`, `rrule_text`, `run_native_async`, plus
`request_access`/`request_access_each`/`bootstrap` (referenced by `doctor.py` and
`__init__.py`, not directly read this session — locate via `grep -n "request_access\|bootstrap" macos_apps_mcp/runtime.py`).

**What stays in `runtime.py`** (research-verified target: `run_native, on_worker,
app_process_info, terminate_children, tracked_run, run_osascript, body_file,
verify_sqlite_schema, read_via_sqlite, mac_region, log` — ~10 public names, GATE-02):

**Module header pattern** (`macos_apps_mcp/runtime.py:16-38`):
```python
from __future__ import annotations

import contextlib
import logging
...
import EventKit as EK
import Foundation as F

from .contracts import CLEAR_RECURRENCE, Recurrence
from .errors import (
    ...
)
```
`eventkit.py` takes this exact header shape but drops the non-EventKit stdlib imports
(`sqlite3`, `subprocess`, `tempfile` stay in `runtime.py`); it keeps `EventKit as EK`,
`Foundation as F`, and the `.contracts`/`.errors` imports the moved functions need.

**Store ownership pattern** (`macos_apps_mcp/runtime.py:106-121`, body copied verbatim):
```python
_store: EK.EKEventStore | None = None


def _on_worker() -> bool:
    return threading.current_thread().name.startswith("mac-native")


def store() -> EK.EKEventStore:
    """The one process-wide EKEventStore, created lazily on the worker thread.
    ...
    """
    global _store
    if not _on_worker():
        raise RuntimeError(
```
`_on_worker` moves WITH `store()` — it exists only to guard this one function. Keep the
`# ponytail`-style global-state comment intact; it documents why this can't be a
dataclass field.

**Adapter-side import fix** (calendar.py/reminders.py, both files, applied by card 7):
```python
# BEFORE (calendar.py:23-33)
from ..runtime import (
    container_id, epoch_nsdate, from_nsdate, persisted_recurrence_signature,
    recurrence_signature, run_native, store, to_nsdate, to_recurrence_rule,
)

# AFTER — run_native stays a runtime import; everything else moves to eventkit
from ..eventkit import (
    container_id, epoch_nsdate, from_nsdate, persisted_recurrence_signature,
    recurrence_signature, store, to_nsdate, to_recurrence_rule,
)
from ..runtime import run_native
```
Apply the same split to `reminders.py:21-32` (`due_components`, `rrule_text`,
`run_native_async` move too; `run_native` stays).

**Doctor.py import collision (Pitfall 6, sequencing note):** card 5's edit to
`doctor.py`'s import block must start from what card 7 leaves behind
(`from .eventkit import request_access_each` / `from .runtime import app_process_info,
run_native, run_osascript`), not from the pre-card-7 line the spike diff shows. Do not
apply spike 5's doctor.py import diff literally.

---

### `macos_apps_mcp/tiers.py` (new — card 5)

**Analog:** `macos_apps_mcp/server.py:61-104` (`_read_only`, `_allow_send`) — bodies copied
verbatim from current `develop`, not from `spike/arch-review-5-tier-policy@f442d49`.

**Function bodies to move, byte-identical** (`macos_apps_mcp/server.py:61-104`):
```python
def _read_only() -> bool:
    """True when MACOS_APPS_READ_ONLY is set; writes are then not registered. ..."""
    val = os.environ.get("MACOS_APPS_READ_ONLY", "").strip().lower()
    return val in ("1", "true", "yes")


def _allow_send(adapter: str) -> bool:
    """True when OUTBOUND is enabled for `adapter` (#104). ..."""
    if _read_only():
        return False
    val = os.environ.get("MACOS_APPS_ALLOW_SEND", "")
    if not val and deploy.is_daemon_role():
        val = deploy.allow_send_file()
    val = val.strip().lower()
    if val in ("1", "true", "yes", "all"):
        return True
    return adapter in {p.strip() for p in val.split(",") if p.strip()}
```
Rename to public `read_only()`/`allow_send(adapter)` in `tiers.py` (module-qualified
callers: `tiers.read_only()`, matching the `from .. import runtime` qualified-import
convention already enforced by `tests/test_native_seam.py`). `tiers.py` needs `from . import
deploy` (same import `server.py` already has at line 17).

**Pitfall 3 — do NOT port the outbound ledger into `tiers.py`.** Per RESEARCH.md's Pitfall
3 and Assumption A2, `_SEND_ADAPTERS`/`_SEND_REGISTERED`/`admit_send()`/`outbound_status()`
belong on card 2's `registry.py` (the "one record" owner), not duplicated here. `tiers.py`
after card 2 lands should hold ONLY `read_only()`/`allow_send()` — the pure gate
predicates from `server.py:61-104` above, nothing else. Plan card 5 to land the ledger
provisionally if needed for sequencing, but card 2's integration task must delete it from
`tiers.py` once `registry.py` exists.

**Doctor's consumption point** (`macos_apps_mcp/doctor.py:297-304`, the import-cycle site
to remove):
```python
def _outbound_state() -> dict[str, list[str]]:
    """``server.outbound_status()`` — registered vs configured outbound adapters
    (#130, C6). Imported LOCALLY: ...  this is the one place doctor.py reaches into
    server.py, and it does so lazily."""
    from . import server

    return server.outbound_status()
```
Replace the body with a direct call into `registry.outbound_status()` (or `tiers` +
`registry` composed), and delete the local `from . import server` import entirely — this
is GATE-03's literal target.

---

### `macos_apps_mcp/notices.py` (new — card 5)

**Analog:** `macos_apps_mcp/audit.py:231-283` (`AuditMiddleware`) — same FastMCP
`Middleware` subclass shape, same registration pattern in `server.py`.

**Middleware skeleton to follow** (`macos_apps_mcp/audit.py:231-247`):
```python
class AuditMiddleware(Middleware):
    """... Central seam — adapters hold no audit logic. All failures are swallowed.

    ``write_tools`` and ``snapshot_sources`` are registries owned by the caller
    (server.py's tool decorators fill them during registration, before it wires this
    middleware); the middleware reads them per call, so construction order can't
    break it either way.
    """

    def __init__(
        self, write_tools: set[str], snapshot_sources: dict[str, Snapshotter]
    ) -> None:
        self._write_tools = write_tools
        self._snapshot_sources = snapshot_sources

    async def on_call_tool(self, context, call_next):
        tool = context.message.name
        ...
        result = await call_next(context)
        ...
        return result
```
`notices.UntrustedDataNotice` follows this exact constructor-takes-a-registry-view /
`on_call_tool(context, call_next)` shape — GATE-03 moves the notice middleware currently
embedded in `server.py` (find it via `grep -n "notice\|Notice" macos_apps_mcp/server.py`
before writing the plan step; not directly read this session, so verify the exact
current body at plan time rather than assuming it matches audit.py's shape 1:1).

**Wiring pattern in server.py** (mirror wherever `AuditMiddleware` is instantiated —
`grep -n "AuditMiddleware(" macos_apps_mcp/server.py` — `notices.UntrustedDataNotice`
gets the same `mcp.add_middleware(...)`-style call).

---

### `macos_apps_mcp/registry.py` (new — card 2)

**Analog:** `macos_apps_mcp/server.py:149-286` (the five hand-maintained name sets and
the `_read_tool`/`_write_tool`/`_additive_tool`/`_send_tool` decorators) — copy the
decorator bodies from current `develop`; adapt to build one `ToolRecord` per call instead
of touching five sets.

**Current decorator shapes to preserve as thin aliases** (per CONTEXT.md's discretion
note — "Keep `@_read_tool`, `@_write_tool`, `@_additive_tool` and `@_send_tool` as thin
aliases over one `_tool(...)` record"), verbatim from `macos_apps_mcp/server.py:159-196`:
```python
def _read_tool(fn):
    """Register a read tool, wrapped so typed native failures surface as directives.
    Annotated read-only (#57)."""
    return mcp.tool(annotations=_READ_ANNOTATIONS)(_guard(fn))


def _write_tool(
    fn=None, *, snapshot: Snapshotter | None = None, open_world: bool = False
):
    """Register a write that modifies/overwrites/deletes existing state — skipped in
    read-only mode (safe-deploy guard). ..."""

    def deco(f):
        if _read_only():
            return f
        _WRITE_TOOLS.add(f.__name__)
        if snapshot is not None:
            _SNAPSHOT_SOURCES[f.__name__] = snapshot
        ann = _DESTRUCTIVE_ANNOTATIONS
        if open_world:
            ann = {**ann, "openWorldHint": True}
        return mcp.tool(annotations=ann)(_guard(f))

    return deco(fn) if fn is not None else deco
```
Rewrite: each becomes `_read_tool = functools.partial(_tool, tier="read")`-style
(exact mechanism is the planner's call), where `_tool(...)` builds a `registry.ToolRecord`
(`tier`, `adapter`, `permission`, `audit`, `notice=True`, `backup_notice=False`,
`snapshot=None`, `open_world=False`, `guard=True`, `registered: bool`) and stores it in
`registry.TOOLS[name]` — a gated-off tool (read-only mode, send-disabled adapter) is
still recorded with `registered=False`, never simply absent from the dict (GATE-04,
the security "elevation of privilege" mitigation in RESEARCH.md's threat table).

**Verb-derivation pattern — REQUIRED CHANGE from the spike, not a straight port**
(RESEARCH.md's verified example, adapted from `spike/arch-review-2-registration-record`
but with the fallback removed per CONTEXT.md's explicit instruction):
```python
def derive_audit_verb(name: str, tier: Tier, explicit: str | None) -> str | None:
    if tier == "read":
        if explicit is not None:
            raise TypeError(f"{name}: a read tool carries no audit verb")
        return None
    if explicit is not None:
        return explicit
    if tier == "send":
        return "send"
    for prefix in ("create", "update", "delete", "complete"):
        if name.startswith(prefix):
            return prefix
    raise TypeError(f"{name}: write tool needs an explicit audit= verb")
```
This RAISES instead of the current `_audit_op`'s silent `"write"` fallback
(`macos_apps_mcp/audit.py:185-200`, shown below) — CONTEXT.md's discretion note requires
the fallback GONE, and the spike's own diff keeps it, so this is a deliberate departure
from the spike recipe.

**Current `_audit_op` to replace** (`macos_apps_mcp/audit.py:185-200`):
```python
def _audit_op(tool: str) -> str:
    for prefix in ("create", "update", "delete"):
        if tool.startswith(prefix):
            return prefix
    return {
        "complete_reminder": "complete",
        "run_shortcut": "action",
        "safari_open": "open",
        "mail_reply": "reply",
        "send_mail": "send",
        "reply_all": "send",
        "forward_mail": "send",
    }.get(tool, "write")
```
`AuditMiddleware.on_call_tool` (`macos_apps_mcp/audit.py:274`) currently calls
`_audit_op(tool)`; after card 2, it must read the verb off `registry.TOOLS[tool].audit`
instead — a per-tool FACT stated once at registration, not re-derived from the name at
audit time (RESEARCH.md's "Key insight").

**Audit-verb map per CONTEXT.md's discretion note** (apply at each tool's `@_tool(...,
audit=...)` call site, replacing the derived-from-prefix guesses above): `move_mail`→
`move`, `trash_mail`→`trash`, `mail_undo`→`undo`, `export_mail`→`export`,
`save_mail_attachment`→`save`, music/volume/mode tools→`play`/`set`, `create_contact`
must carry an explicit verb (currently uncovered by `_audit_op`'s dict — it falls
through to `create` today via the prefix check, which is fine; just make it explicit in
the record).

**D-04's fail-closed dry-run-default test (GATE-05, Wave 0 gap — no spike delivers
this):** a new test in `tests/test_registry.py` must assert every `ToolRecord` in the
"removes or replaces content" class defaults `dry_run=True`, AND fail closed for a tool
merely named `delete_*` even if its record forgets to declare the class — e.g.:
```python
def test_delete_prefixed_tools_default_dry_run_true():
    sig_defaults = {  # read via inspect.signature on the dispatched fn
        name: rec for name, rec in registry.TOOLS.items() if name.startswith("delete_")
    }
    for name, rec in sig_defaults.items():
        assert _dry_run_default(rec.fn) is True, f"{name} must default dry_run=True"
```
Model this on `tests/test_tool_annotations.py`'s existing pattern of walking
`_WRITE_TOOLS`/`_DESTRUCTIVE_TOOLS` frozensets and asserting a property per tool
(`tests/test_tool_annotations.py:15-51`, shown above in File Classification).

---

### `tests/envelope.py` (new — card 3)

**Analog:** `tests/test_mail_search.py:1-80+` (`_fake_envelope`, private today) — promote
verbatim, widen schema, do not rewrite the row-building logic.

**Fixture shape to promote** (`tests/test_mail_search.py:29-80`, excerpted):
```python
def _fake_envelope(path):
    """A minimal Envelope Index with the fingerprinted tables + columns. ..."""
    c = sqlite3.connect(path)
    c.executescript(
        f"""
        CREATE TABLE subjects(ROWID INTEGER PRIMARY KEY, subject TEXT);
        CREATE TABLE addresses(ROWID INTEGER PRIMARY KEY, address TEXT, comment TEXT);
        CREATE TABLE mailboxes(ROWID INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE message_global_data(
            ROWID INTEGER PRIMARY KEY, message_id_header TEXT);
        CREATE TABLE recipients(ROWID INTEGER PRIMARY KEY, message INT, address INT);
        CREATE TABLE attachments(ROWID INTEGER PRIMARY KEY, message INT, name TEXT);
        CREATE TABLE messages(
            ROWID INTEGER PRIMARY KEY, subject INT, sender INT, global_message_id INT,
            mailbox INT, date_received INT, date_sent INT, read INT, flagged INT,
            deleted INT, conversation_id INT);
        ...
        """
    )
```
Rename to `fake_envelope` (public, module-level in `tests/envelope.py`), and it must
build against a WIDER schema — add `size`, `message_id`, `subject_prefix` columns to
`messages`, a `message_references` table (`ROWID`, `message`, `reference`), and widen
`recipients` to `(message, address, type, position)` — per Pitfall 2 below.

**Already-existing infrastructure to route through, not duplicate**
(`tests/conftest.py:70-140`, `sequoiaify_envelope` + `envelope_mode` fixture — landed by
#201, independent of this phase, shown in full above): card 3's fixture module imports
these from `tests.conftest` rather than re-implementing the Sequoia-shape conversion.

**`HEADER_FINGERPRINT` coverage gap (Pitfall 2, current state)**
(`macos_apps_mcp/adapters/mail_index.py:26-49`, read in full this session):
```python
HEADER_FINGERPRINT: dict[str, set[str]] = {
    "messages": {
        "ROWID", "subject", "sender", "global_message_id", "mailbox",
        "date_received", "date_sent", "read", "flagged", "deleted", "conversation_id",
    },
    "subjects": {"ROWID", "subject"},
    "addresses": {"ROWID", "address", "comment"},
    "mailboxes": {"ROWID", "url"},
    "message_global_data": {"ROWID", "message_id_header"},
    "recipients": {"message", "address"},
    "attachments": {"ROWID", "message", "name"},
}
```
Add (per RESEARCH.md's Pitfall 2, quoting the spike's own docstring admission): `size`,
`message_id`, `subject_prefix` to `messages`; a new `message_references` entry
(`{"ROWID", "message", "reference"}`); widen `recipients` to `{"message", "address",
"type", "position"}`. `query_sent_triage` (`macos_apps_mcp/adapters/mail_index.py:1136`)
and `query_duplicate_rows` (`:1169`) are the two executors that read the currently
uncovered columns — trace their SQL builders (`build_sent_triage_query`,
`build_duplicate_rows_query`, `build_sent_recipients_query`) for the exact column list
before writing the coverage test.

**Coverage-assertion test (CONTEXT.md's discretion note: "a test asserts that
coverage")** — model on `tests/test_native_seam.py`'s `ast`-walk pattern
(`tests/test_native_seam.py:15-38`, shown above): parse each `query_*` function body via
`ast`, extract every `Attribute`/subscript column reference against a known table alias,
and assert it's a subset of `HEADER_FINGERPRINT[table]`.

---

### `macos_apps_mcp/adapters/mail_recover.py` (card 4)

**Analog:** itself — `check_batch` (`:141`), `preview` (`:332-356`), `recoverable`
(`:365-467`), all read in full this session.

**Current `preview()` — the shape `recoverable(dry_run=True)` must subsume**
(`macos_apps_mcp/adapters/mail_recover.py:332-356`):
```python
def preview(op: str, targets, *, destination: str | None = None) -> dict:
    """The ONE dry-run envelope every destructive mail write answers with. ..."""
    _check_op(op)
    items = check_batch(targets)
    out: dict = {
        "dry_run": True, "op": op, "count": len(items),
        "would_affect": [t.as_dict() for t in items],
    }
    if destination is not None:
        out["destination"] = destination
    return out
```
**Current `recoverable()` signature to extend with `dry_run`/`present`**
(`macos_apps_mcp/adapters/mail_recover.py:365-396`, full docstring read):
```python
def recoverable(
    op: str, targets, act, *,
    destination: str | None = None, backup: bool = True, allow_lossy: bool = False,
) -> dict:
    """**backup → log → act**, then report what actually happened. ..."""
    _check_op(op)
    items = check_batch(targets)
```
Per RESEARCH.md's Pattern 3, add `dry_run: bool = False, present: Callable | None =
_NO_READ` — `present` is REQUIRED to be stated (an explicit `None` is the deliberate
"this op has no read" escape hatch used by `dedupe_batch`, never a silent default). When
`dry_run=True`, call `present(items)` if given, then return `preview(op, items,
destination=destination)`'s shape without touching `act`/`_backup`/`audit_write`.

**The exact bug this fixes** (`macos_apps_mcp/adapters/mail.py:1478-1479`, verified this
session):
```python
if dry_run:
    return mail_recover.preview("dedupe", targets, destination=trash)
```
This calls `preview()` directly with NO presence check — `dedupe_batch(dry_run=True)`
reports "planned" for targets nobody verified exist. Fix: route through
`mail_recover.recoverable(..., dry_run=dry_run, present=None)` per the spike's pattern
(present=None here is deliberate: dedupe's caller already verifies via sqlite before a
real run — this is the documented escape hatch, not the bug).

**Refusal-text fix (Pitfall 4, small fix per CONTEXT.md)** — locate `check_batch`'s
`BatchTooLarge` message (`macos_apps_mcp/adapters/mail_recover.py:141-158`, referenced by
RESEARCH.md at those lines) and make the "every target is backed up to disk" claim
conditional or generic, since `update_mail_status` calls `check_batch` too
(`macos_apps_mcp/adapters/mail.py:1560`) and never backs anything up.

---

### `macos_apps_mcp/adapters/mail.py` (cards 4, 9)

**Analog:** itself — `dedupe_batch` (`:1446-1501`), `_DEDUPE_TIMEOUT`/`_DEDUPE`
(`:468-609`), both read in full this session.

**The `_DEDUPE` timeout bug** (`macos_apps_mcp/adapters/mail.py:468` and `:515`):
```python
_DEDUPE_TIMEOUT = 900.0
...
_DEDUPE = (
    STRIP_FRAMING + "\n\n" + mail_addressing.MAILBOX_REF + """
on run argv
  ...
  with timeout of 600 seconds
  tell application "Mail"
    ...
```
Fix: raise `600` → `900` (or higher) on the `with timeout of` line inside the `_DEDUPE`
template string. Do not lower `_DEDUPE_TIMEOUT`. This is a one-line string edit; the
general tripwire (below) is the structural fix.

**GATE-10 tripwire (Wave 0, no spike delivers a clean version — card 9's wrapper was
withdrawn per CONTEXT.md).** Inventory every `with timeout of N seconds` occurrence
across `macos_apps_mcp/adapters/mail.py` (lines `140, 174, 219, 230, 258, 333, 416, 515,
609` per this session's grep) and its call-site `timeout=` kwarg
(`runtime.run_osascript(TEMPLATE, ..., timeout=X)`), then assert `N >= X` for every pair
in `tests/test_timeout_tripwire.py`. RESEARCH.md's Assumption A1 leaves the
implementation strategy (AST cross-reference vs. hand-maintained mapping table) to the
planner — a hand-maintained table keyed by template constant name is the simpler,
acceptable fallback if AST matching proves fragile against the multi-line script
strings. Model the test file's shape on `tests/test_native_seam.py`'s `ast.parse` +
`ast.walk` pattern (shown above).

---

### `macos_apps_mcp/adapters/notes.py` (card 1, D-02)

**Analog:** itself — `delete()` (`:709-740`), `snapshot()` (`:681-692`), import block
(`:15-31`), all read in full this session.

**Import fix (card 1, GATE-01)** — current (`macos_apps_mcp/adapters/notes.py:30`):
```python
from ..runtime import body_file, read_via_sqlite, run_osascript
```
Fix, matching the already-correct `mail.py:73` shape:
```python
from .. import runtime
```
then every call site (`run_osascript(...)` → `runtime.run_osascript(...)`, same for
`body_file`/`read_via_sqlite`) is qualified — this is the widened-glob target
`tests/test_native_seam.py` (card 1) checks against `adapters/*.py`, not just `mail*.py`.

**D-02's `update_note` dry-run — model on the EXISTING `delete()` dry-run guard, same
file** (`macos_apps_mcp/adapters/notes.py:709-740`, full body read above): the delete
path resolves the target BEFORE branching on `dry_run`, and returns the SAME
`deletion_result`-shaped envelope whether previewing or acting — this is the template
for `update_note`'s new preview: resolve current title (`self._read_title_by_id` /
`snapshot()`, `:681-692`) and body size, build a preview dict shaped like
`deletion_result` (`macos_apps_mcp/contracts.py:93-100`, shown below), and make NO Notes
write on the preview path — reusing `snapshot()` for the "current title" half, since
D-02's CONTEXT.md note explicitly says the before-state is title-only and a read is
allowed in this specific preview.

**`deletion_result` envelope to reuse the SHAPE of, not the function itself** (D-02 needs
a new envelope since `update_note` isn't a delete — `macos_apps_mcp/contracts.py:93-100`):
```python
def deletion_result(ident: str, preview: Pointer | None) -> dict:
    """The ONE wire shape for every delete tool (C5d): a dry run answers
    ``{"dry_run": True, "would_delete": <pointer dict>}``; a real delete answers
    ``{"deleted": ident}``. Adapters own ``dry_run`` and build this envelope —
    tools stay one-line delegations."""
    if preview is not None:
        return {"dry_run": True, "would_delete": preview.as_dict()}
    return {"deleted": ident}
```
D-02's preview envelope follows the same `{"dry_run": True, ...}` wire convention but
needs a NEW shape (e.g. `{"dry_run": True, "would_update": {"current": {...}, "new":
{...}}}`) since it compares two states, not one pointer — this is a new contracts
function, not a reuse of `deletion_result` itself.

**Server-side wiring to update** (`macos_apps_mcp/server.py:1264-1297`, both `delete_note`
and `update_note` tool wrappers read in full above): `update_note`'s `@_additive_tool` →
`@_write_tool(snapshot=_notes)` (it becomes destructive-annotated, matching `delete_note`'s
existing pattern at line 1264), and its signature gains `dry_run: bool = True`.

---

### `macos_apps_mcp/adapters/calendar.py` (card 1, D-01)

**Analog:** itself — `delete_event()` (`:488-509`, full body read above).

**Current `delete_event` — already has the dry-run BRANCH, only the DEFAULT changes**
(`macos_apps_mcp/adapters/calendar.py:488-507`):
```python
def delete_event(
    self, ident: str, span: Span | None = None, dry_run: bool = False
) -> dict:
    """Delete an event by id → the ``deletion_result`` envelope (C5d). ..."""

    def work():
        s = store()
        e = _resolve_event(s, ident)
        ek_span = _resolve_span(e, span)
        if dry_run:
            return deletion_result(ident, _event_pointer(e))
        ok, err = s.removeEvent_span_commit_error_(e, ek_span, True, None)
        if not ok:
            raise refused_write("event delete", "calendar", err)
        return deletion_result(ident, None)

    return run_native(work)
```
D-01 changes only `dry_run: bool = False` → `dry_run: bool = True` here AND at the
server.py wrapper (`macos_apps_mcp/server.py:1254-1261`, `delete_event`, shown above) —
the branch logic itself is untouched; this is a pure default-value flip plus a docstring
update.

---

### `macos_apps_mcp/adapters/{contacts,photos,safari,messages,music}.py` (card 1)

**Analog:** `macos_apps_mcp/adapters/mail.py:73` and `mail_addressing.py:37` and
`mail_triage.py:24` and `mail_outgoing.py:51` and `mail_drafts.py:25` and
`mail_attachments.py:18` — SIX files under `adapters/` already do this correctly
(`from .. import runtime`); these five do not.

**Current (wrong) shape, verified this session across all five files:**
```python
# contacts.py:16, photos.py:13, safari.py:11, music.py:16
from ..runtime import run_osascript
# messages.py:23
from ..runtime import mac_region, read_via_sqlite, run_osascript
```
**Target shape (copy from `mail.py:73`):**
```python
from .. import runtime
```
then every `run_osascript(...)` / `mac_region(...)` / `read_via_sqlite(...)` call site in
each file becomes `runtime.run_osascript(...)` etc. This is a mechanical, per-file
find-and-qualify — the widened `tests/test_native_seam.py` glob (`adapters/*.py`, not
`mail*.py`) is what catches a regression.

---

### `macos_apps_mcp/adapters/shortcuts.py` (card 1)

**Analog:** `macos_apps_mcp/adapters/mail.py:73` (same fix, different seam name).

**Current** (`macos_apps_mcp/adapters/shortcuts.py:21`):
```python
from ..runtime import tracked_run
```
**Target:**
```python
from .. import runtime
```
with call sites becoming `runtime.tracked_run(...)`. GATE-01 explicitly names
`shortcuts.tracked_run` as in scope for the widened seam check (per phase context), and
`doctor.py` (`grep -n "tracked_run\|run_osascript" macos_apps_mcp/doctor.py` — not
directly read this session, verify at plan time) needs the same qualified-import
treatment if it reaches these names by name today.

---

### `tests/conftest.py` (card 1 — Pitfall 1, Wave 0)

**Analog:** itself — `_no_real_osascript` (`:143-162`, read in full above), the
autouse-fixture pattern to clone for `body_file`/`tracked_run`.

**Current fixture — locks ONLY `run_osascript`** (`tests/conftest.py:143-162`):
```python
@pytest.fixture(autouse=True)
def _no_real_osascript(request, monkeypatch):
    """Fail CLOSED on the native seam: a unit test that forgets to fake it raises
    instead of spawning osascript against real Mail (#176). ..."""
    if "integration" in request.keywords:
        return

    def _refuse(*_args, **_kwargs):
        raise AssertionError(
            "a unit test reached run_osascript — fake it with "
            "monkeypatch.setattr(runtime, 'run_osascript', ...)"
        )

    monkeypatch.setattr(runtime, "run_osascript", _refuse)
```
**Required extension (Pitfall 1 — the spike's conftest diff touches only the docstring,
never adds the runtime lock for the other two seam names):** add sibling
`monkeypatch.setattr(runtime, "body_file", _refuse)` and
`monkeypatch.setattr(runtime, "tracked_run", _refuse)` calls in the SAME fixture (or two
autouse siblings following the identical shape) — mirroring the `_refuse` closure
exactly, with a name-specific assertion message (`"reached body_file"` /
`"reached tracked_run"`) so a failure is legible.

---

### `tests/test_native_seam.py` (card 1)

**Analog:** itself — the current `_SEAM`/`_MAIL_MODULES` glob (`:20-25`, read in full
above), to be widened.

**Current — Mail-only glob:**
```python
_SEAM = frozenset({"run_osascript", "body_file"})
_MAIL_MODULES = sorted(
    (pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters").glob(
        "mail*.py"
    )
)
```
**Target (widened per GATE-01):**
```python
_SEAM = frozenset({"run_osascript", "body_file", "tracked_run"})
_MODULES = sorted(
    (pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters").glob("*.py")
) + [pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "doctor.py"]
```
Keep the same `ast.walk`/`ImportFrom` check (`:29-38`) and the "tripwire sees the
modules" sanity assertion (`:41-43`), raising its `>= 3` floor to reflect the new,
larger module count (`>= 9` for adapters alone).

---

## Shared Patterns

### Qualified native-seam import (`from .. import runtime`)
**Source:** `macos_apps_mcp/adapters/mail.py:73`, `mail_addressing.py:37`,
`mail_triage.py:24`, `mail_outgoing.py:51`, `mail_drafts.py:25`, `mail_attachments.py:18`
(six already-correct exemplars).
**Apply to:** every `macos_apps_mcp/adapters/*.py` that still does
`from ..runtime import <name>` (card 1) — `contacts.py`, `photos.py`, `safari.py`,
`messages.py`, `music.py`, `notes.py`, `shortcuts.py` (7 files, verified this session).
```python
from .. import runtime
...
runtime.run_osascript(...)
```

### Dry-run envelope shape (`deletion_result`)
**Source:** `macos_apps_mcp/contracts.py:93-100`.
**Apply to:** `delete_event`, `delete_draft`, `delete_note` (D-01, no shape change —
default flips only) and as the STRUCTURAL model (not the literal function) for
`update_note`'s new D-02 preview envelope.
```python
def deletion_result(ident: str, preview: Pointer | None) -> dict:
    if preview is not None:
        return {"dry_run": True, "would_delete": preview.as_dict()}
    return {"deleted": ident}
```

### Tool registration decorator (`@_read_tool`/`@_write_tool`/`@_additive_tool`)
**Source:** `macos_apps_mcp/server.py:159-230`.
**Apply to:** every `@mcp.tool` registration; card 2 rewrites the decorator BODIES (one
`registry.ToolRecord` instead of five sets) while keeping these exact names/call sites
unchanged in every tool's own definition.

### Error-as-result guard (`_guard`)
**Source:** `macos_apps_mcp/server.py:106-126`.
**Apply to:** unchanged this phase — every tool wrapper still routes through `_guard`;
card 2's `_tool(...)` must keep calling it, since `NativeError`/`ValueError` → `ToolError`
conversion is the one place typed native failures become agent-directed text.

### Audit verb as a stated fact, not a name-derived guess
**Source:** `macos_apps_mcp/audit.py:185-200` (`_audit_op`, to be REPLACED, not extended)
and `AuditMiddleware.on_call_tool` (`:274`).
**Apply to:** `registry.py`'s `ToolRecord.audit` field, populated at each `@_tool(...,
audit="<verb>")` call site (card 2); `AuditMiddleware` reads `registry.TOOLS[tool].audit`
instead of calling `_audit_op(tool)`.

## No Analog Found

None. Every new module in this phase is a SPLIT or PROMOTION of code that already exists
in current `develop` (runtime.py → eventkit.py, server.py's inline sets → registry.py,
server.py's inline predicates → tiers.py, test_mail_search.py's private fixture →
tests/envelope.py) — there is no green-field file in this phase with zero current-codebase
precedent. Two items have NO spike precedent either (Wave 0 gaps, RESEARCH.md): the
`tests/test_timeout_tripwire.py` GATE-10 test and the `_no_real_osascript` extension in
`tests/conftest.py` (Pitfall 1) — both are modeled on `tests/test_native_seam.py`'s
existing `ast`-walk shape, cited above, not left unmapped.

## Metadata

**Analog search scope:** `macos_apps_mcp/` (all adapters, `runtime.py`, `server.py`,
`doctor.py`, `audit.py`, `contracts.py`), `tests/` (`conftest.py`,
`test_native_seam.py`, `test_mail_search.py`, `test_tool_annotations.py`) — all read
directly from current `develop` HEAD this session, never from a spike branch's checked-out
tree.
**Files scanned:** 26 target files + 12 current-codebase analog files read/grepped in full.
**Pattern extraction date:** 2026-09-25
**Tracked-source gate:** every analog path above is a normal tracked file in this
repository's own git history (`git ls-files` covers all of `macos_apps_mcp/` and
`tests/`) — no `.gsd/capabilities/` mirror or plugin-synced path is involved; this repo is
the target repo itself, not a plugin consuming another repo's capability.
