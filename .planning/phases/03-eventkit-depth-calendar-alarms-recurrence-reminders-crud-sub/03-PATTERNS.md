# Phase 3: EventKit Depth - Pattern Map

**Mapped:** 2026-10-05
**Files analyzed:** 14 (4 new, 10 modified)
**Analogs found:** 13 / 14
**Tracked-source gate:** all analog paths below passed `git ls-files` (checked for `notes.py`, `eventkit.py`, `mail_index.py`, `test_notes.py`; the rest are core package files). No gitignored mirror paths.

Line numbers are from the working tree at mapping time. Re-check before quoting.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `macos_apps_mcp/contracts.py` (Recurrence BY*, `CalendarEventData.alarms`, `Pointer` fields, `deletion_result`) | model | transform | itself (`Recurrence`, `Pointer.as_dict`, `deletion_result`) | exact |
| `macos_apps_mcp/errors.py` (+ subtasks-refusal class) | model (error) | request-response | `SpanRequired` (errors.py:77-82) | exact |
| `macos_apps_mcp/eventkit.py` (9-arg rule, canonical dict, `rrule_text`) | utility | transform | itself, lines 196-254 | exact |
| `macos_apps_mcp/adapters/calendar.py` (alarms, folder, delete gone-check) | service | CRUD | itself (`_apply_event`, `delete_event`) | exact |
| `macos_apps_mcp/adapters/reminders.py` (`delete_reminder`, `create_reminder_list`, join, snapshotter) | service | CRUD | `calendar.delete_event` + own `_fresh_item` | role-match |
| `macos_apps_mcp/adapters/reminders_store.py` (NEW) | service (sqlite sidecar) | batch read | `notes.py` fingerprint + `read_via_sqlite`; `mail_index.py` | role-match |
| `macos_apps_mcp/server.py` (tools, annotations, docstrings) | route (tool layer) | request-response | `delete_event` registration (server.py ~1207) | exact |
| `macos_apps_mcp/registry.py` | config | n/a | derives from name prefix (registry.py ~73-90, ~140-148) | exact (no code change expected) |
| `tests/test_reminders_store.py` (NEW) | test | batch read | `tests/test_notes.py::_make_notestore` (~244) | exact |
| `tests/_fakes.py` (`fake_rule` BY* defaults) | test | n/a | itself | exact |
| `tests/test_calendar.py`, `test_reminders.py` (`calendar()` on fakes, new cases) | test | CRUD | `_fake_event` (test_calendar ~34), `_patch_read` (test_reminders ~141) | exact |
| `tests/test_contracts.py`, `test_eventkit.py`, `test_server.py`, `test_registry.py`, `test_tool_annotations.py` (pinned-test edits) | test | n/a | themselves | exact |
| `tests/test_integration.py` (device tests, teardown) | test | CRUD | teardown at ~30-48 | role-match |
| DTSTART membership check (in `contracts.py`) | utility | transform | none | no analog |

## Pattern Assignments

### `macos_apps_mcp/adapters/reminders_store.py` (NEW sidecar, batch read)

**Analog:** `macos_apps_mcp/adapters/notes.py` (fingerprint + path constant + `read_via_sqlite`), `adapters/mail_index.py` (sidecar beside adapter).

**Imports** (notes.py:15-31, adapt):
```python
from __future__ import annotations
from pathlib import Path
from ..errors import FullDiskAccessDenied, NativeError   # check exact names in errors.py
from ..runtime import read_via_sqlite
```
Unqualified `read_via_sqlite` import is allowed (not in `test_native_seam._SEAM`).

**Fingerprint** (notes.py:58-76 shape: `dict[str, set[str]]`, table to columns, comment per column):
```python
_FINGERPRINT = {
    "Z_PRIMARYKEY": {"Z_ENT", "Z_NAME"},
    "ZREMCDOBJECT": {"Z_ENT", "ZNAME1", "ZREMINDER3", "ZMARKEDFORDELETION"},
    "ZREMCDREMINDER": {"Z_PK", "ZCKIDENTIFIER", "ZPARENTREMINDER", "ZMARKEDFORDELETION"},
}
```
SQL strings `_TAGS`, `_PARENTS`, `_SUBTASKS_OF`: copy verbatim from RESEARCH Pattern 3 (bound `?` for the parent id; `Z_ENT` from `Z_PRIMARYKEY`; tombstone filter on both rows).

**Core pattern** (notes.py:570-576): `read_via_sqlite(PATH, _FINGERPRINT, read_fn, immutable=False)`. Drop `fallback=` (D-13: no fallback; errors re-raise typed). `read_fn(conn)` returns plain data (dict of id to tags tuple, dict of id to parent id).

**Path function** (differs from notes.py:48 constant, per Pitfall 5): a function, patchable by tests, using `os.scandir` (NOT `Path.glob`) on `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores`, picking the largest `Data-*.sqlite`. Map `PermissionError` to `FullDiskAccessDenied`; empty or missing dir to bare `NativeError("Reminders store not found")`.

**Runs on worker:** `read_via_sqlite` runs inline when already on the worker (runtime.py:433-462), so `reminders()` and `delete_reminder` call it inside their `run_native` block.

**Tag text hygiene:** pass through `text.sanitize_line` / `clean_summary` (untrusted text reaches the model).

---

### `macos_apps_mcp/adapters/reminders.py` (service, CRUD)

**Analog:** `adapters/calendar.py::delete_event` (lines 488-509) for the delete shape; own `_fresh_item` (reminders.py:119-127) for the gone-check.

**Imports** (reminders.py:9-33): already has `EK`, `Pointer`, `ReminderData`, `resolve_container`, `verify_persisted`, `refused_write`, `store`, `run_native`, `clean_summary`. Add: `reminders_store`, `read_result`, `deletion_result`, `WriteRefused`, the new subtasks error, `dataclasses.replace`.

**Pointer builder** (reminders.py:56-62), extend with keywords (Pitfall 9, Pointer is frozen/slotted):
```python
def _reminder_pointer(item, *, tags=None, parent=None) -> Pointer:
    ident = item.calendarItemIdentifier()
    return Pointer(id=ident, summary=clean_summary(_reminder_summary(item)),
                   deeplink=_reminder_deeplink(ident),
                   folder=container_id(item), tags=tags, parent=parent)
```
`container_id` is already imported (eventkit.py:45-51; returns None when `calendar()` is None).

**Delete shape to copy** (calendar.py:488-509): resolve target, then the refusal, then branch on `dry_run`, then remove, then gone-check.
```python
def work():
    s = store()
    e = _resolve_event(s, ident)
    ek_span = _resolve_span(e, span)      # refusal fires BEFORE the dry_run branch
    if dry_run:
        return deletion_result(ident, _event_pointer(e))
    ok, err = s.removeEvent_span_commit_error_(e, ek_span, True, None)
    if not ok:
        raise refused_write("event delete", "calendar", err)
    return deletion_result(ident, None)
return run_native(work)
```
For `delete_reminder`: replace the span step with `reminders_store` subtasks read (store failure propagates as the typed error, no delete, D-18), raise the subtasks-refusal if `subtasks and not with_subtasks`, use `s.removeReminder_commit_error_`, then `_fresh_item(s, ident) is None` else `VerificationFailed`. Pass subtasks into `deletion_result` (extend it).

**Gone-check primitive** (reminders.py:119-127): `_fresh_item` returns None when gone.

**`reminders()` degrade** (RESEARCH "reminders() degrade"): EventKit read first, then one `try` around path fn plus `read_via_sqlite` catching `NativeError` subclasses, fold the reason into `coverage`, return `read_result(pointers, coverage=...)`. EventKit errors stay outside the `try`.

**`create_reminder_list`:** copy the sketch in RESEARCH "Reminder-list create (D-22)". Verify by id with the same set comprehension `_resolve_list` uses (reminders.py ~110-116). Use `resolve_container` conventions for duplicate-name refusal (raise `ValueError`, agent-directed).

**Snapshotters (D-20):** the existing `RemindersAdapter.snapshot` stays EventKit-only. Add a second small object with `snapshot(ident) -> Pointer | None` for `delete_reminder` that attaches `subtasks`. `AuditMiddleware._safe_snapshot` swallows exceptions into `before=None` (audit.py), so keep store errors out of the shared one.

---

### `macos_apps_mcp/adapters/calendar.py` (service, CRUD)

**Analog:** itself.

**Pointer folder** (calendar.py:81-86): add `folder=container_id(item)`; `container_id` is already imported (line ~22).

**Alarm slot** (calendar.py:209-230): replace the `ponytail: all-day alarm 1440-gotcha (#51)` comment block at the end of `_apply_event` with:
```python
if data.alarms is not None:   # None = untouched, [] = clear (same tri-state as recurrence)
    alarms = [EK.EKAlarm.alarmWithRelativeOffset_(-m * 60.0) for m in data.alarms]
    e.setAlarms_(alarms or None)   # None, never [], clears
```
Recurrence tri-state precedent in the same function:
```python
if data.recurrence is not None:
    e.setRecurrenceRules_([to_recurrence_rule(data.recurrence)])
```

**Verify-after-write** (calendar.py ~312-357): field-dict compare through `errors.verify_persisted`. Add `alarms` (sorted `round(relativeOffset()/60)`) and `absolute_alarms == 0` keys only when `data.alarms is not None`. Call `recurrence_signature(..., include_until=not data.all_day)` (Pitfall 10).

**delete_event gone-check** (Pitfall 6): after `removeEvent_span_commit_error_`, re-run `_resolve_event(s, ident)` and require `ValueError`; else `VerificationFailed`. Do NOT use `_fresh_item` on the base id (series master survives a `this-event` delete).

---

### `macos_apps_mcp/eventkit.py` (utility, transform)

**Analog:** itself, lines 196-254. Keep names; replace bodies.

- `to_recurrence_rule` (lines ~198-212): keep the `end` construction (COUNT or UNTIL); swap the 3-arg `initRecurrenceWithFrequency_interval_end_` for the 9-arg form from RESEARCH Pattern 2. `None`, never `[]`, for an absent part; ordinal 0 for a plain weekday.
- `recurrence_signature` / `persisted_recurrence_signature` (lines ~215-247): both return the same-keyed canonical dict (RESEARCH "Canonical read-back"). Add `include_until: bool` argument. Key sets must be identical on both sides.
- `rrule_text` (lines ~250-254): append BYDAY (`{ordinal}{code}`), BYMONTHDAY, BYMONTH, BYYEARDAY, BYSETPOS parts after INTERVAL, before COUNT, so the `RecurrenceRequired` re-send text round-trips.

---

### `macos_apps_mcp/contracts.py` (model, transform)

**Analog:** itself.

- `_RRULE_SUPPORTED` (line ~305): widen to the D-06 set. Reject BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND, WKST by name with `ValueError` (follow the existing unsupported-key message style in `Recurrence.from_rrule`, lines ~339-399).
- `Recurrence` BY* fields and range validation in `__post_init__` (Pitfall 3). Frozen/slots dataclass; copy the existing validation-in-`__post_init__` style of `ReminderData` (priority bounds, lines ~205 region) and `CalendarEventData`.
- `CalendarEventData.alarms: tuple[int, ...] | None` (lines ~456-470). Validate in `__post_init__`: max 5, ints only, no bool; negative and duplicate refusals are ASSUMED policy (RESEARCH A3/A4, confirm with owner).
- `Pointer` (lines 209-247): add optional `tags`, `parent`, `subtasks`. Emit in `as_dict` only when set, same `if self.x is not None:` shape. Note `as_dict` is annotated `dict[str, str]`; widen to `dict` (Pitfall 4). Update the `folder` comment ("None elsewhere").
- `deletion_result` (lines 93-100): add optional `subtasks` that adds `"subtasks": [p.as_dict() ...]` to the preview and the confirmation.
- DTSTART membership check: see No Analog.

---

### `macos_apps_mcp/errors.py` (error class)

**Analog:** `SpanRequired` (errors.py:77-82):
```python
class SpanRequired(NativeError):
    """..."""
    kind = "span_required"
```
Add e.g. `SubtasksRequired(NativeError)` with `kind = "subtasks_required"`. Message wording per CONTEXT specifics.

---

### `macos_apps_mcp/server.py` (tool layer)

**Analog:** `delete_event` registration (server.py ~1207-1214):
```python
@_write_tool(snapshot=_calendar, adapter="calendar", permission="EventKit")
def delete_event(id: str, span: str | None = None, dry_run: bool = True) -> dict:
    """Delete a calendar event by id. ... `dry_run` DEFAULTS TO TRUE ..."""
```
- `delete_reminder(id, dry_run=True, with_subtasks=False) -> dict`: same decorator, `snapshot=` the new delete snapshotter object, `permission=("EventKit", "Full Disk Access")` (check tuple form against registry). Docstring states both permissions and the tag/subtask write gap.
- `create_reminder_list(name)`: `@_additive_tool(adapter="reminders", permission="EventKit")`.
- `create_event` / `update_event`: add `alarms: list[int] | None = None`, build `CalendarEventData(alarms=...)`.
- `reminders()`: return annotation `dict` (envelope), permission `("EventKit", "Full Disk Access")`, docstring names the new wire shape and the write gap (Pitfall 4, 12).
- Annotations: keep `dict[str, str]` only where no list value can appear; widen to `dict` for `complete_reminder`.

---

### `tests/test_reminders_store.py` (NEW)

**Analog:** `tests/test_notes.py::_make_notestore` (~244-260): build a `tmp_path` sqlite with only the fingerprint columns, insert rows, patch the path function with `monkeypatch`. Rows needed: `Z_PRIMARYKEY` (`REMCDHashtag`, `REMCDReminder`), `ZREMCDOBJECT`, `ZREMCDREMINDER`. Cases: match, missing column gives `SchemaDrift`, tombstones excluded on tag AND reminder rows, subtask query, FDA denial via a faked `PermissionError`.

### Existing test edits (same plan as the code, RESEARCH Pitfall 11)
- `tests/_fakes.py::fake_rule(freq, interval, count)`: add BY* attributes defaulting to `None`; keep the old call signature (7 call sites).
- `tests/test_calendar.py::_fake_event` (~34-41), `_fake_persisted_event`, `tests/test_reminders.py::_fake_reminder`: add `calendar=lambda: SimpleNamespace(calendarIdentifier=lambda: "C-1")`; one test with a `None` calendar.
- Unit tests patch `rem.store` / `rem.run_native` per adapter module (`tests/test_reminders.py::_patch_read`, ~141-155). conftest does not seal EventKit or sqlite.
- `tests/test_registry.py` equality pins (`_DEVELOP_ADDITIVE`, `_DEVELOP_DESTRUCTIVE`, `_DEVELOP_PERMISSION`, `removes_content_tools()`), `tests/test_tool_annotations.py::envelope_only` (+`create_reminder_list`, NOT `delete_reminder`), `tests/test_contracts.py:112` and `tests/test_server.py:560` (BYDAY no longer unsupported, use BYWEEKNO), `tests/test_eventkit.py:101-164` (tuple to dict), `tests/test_server.py:102, 994-1035` (envelope).

## Shared Patterns

### Verify-after-write
**Source:** `errors.verify_persisted(entity, expected, actual)` (errors.py ~124-185), used in calendar.py ~312-357 and reminders.py. Build `expected` and `actual` dicts with identical key sets; compare only fields that were set.

### Typed errors, never silent
**Source:** `errors.py` (`NativeError` subclasses with `kind`), `refused_write(what, noun, err)`. `@_guard` in server.py converts `NativeError` and `ValueError` to `ToolError`. Boundary validation raises `ValueError` with an agent-directed message. Optional-plane failures (store) degrade through `coverage`, never `[]`.

### Native seam
**Source:** `runtime.run_native` (single worker). All EventKit and sqlite work runs inside one `run_native(work)`; `read_via_sqlite` runs inline on the worker.

### Dry-run default and audit verb
**Source:** `registry.py` ~73-90, ~140-148: verb from the name prefix, `delete_*` is the removes-content class with `dry_run=True` default; asserted by `tests/test_registry.py` ~365-377.

### Text hygiene
**Source:** `text.clean_summary` for Pointer summaries; `text.sanitize_line` for tag strings. List titles stay RAW (reminders.py `_list_pointer` comment: the summary is a write key).

### Docstring permission names
**Source:** `tests/test_tool_annotations.py::test_every_tool_docstring_states_permission_and_is_nontrivial`: the docstring must name every permission in the registered tuple ("EventKit", "Full Disk Access").

## No Analog Found

| File / piece | Role | Data Flow | Reason |
|---|---|---|---|
| DTSTART membership check (pure Python, in `contracts.py`) | utility | transform | No date-expansion logic exists. Use RESEARCH D-10 plus spike `probe_eventkit.py` `parse`/`to_ek`/`from_ek` under `.claude/skills/spike-findings-macos-apps-mcp/sources/003-eventkit-allday-rrule/`. Test against `python-dateutil` (dev group) and hand-computed dates where dateutil diverges. |

## Metadata

**Analog search scope:** `macos_apps_mcp/` (adapters, eventkit, contracts, errors, runtime, server), `tests/`, phase CONTEXT and RESEARCH.
**Files scanned:** about 12 read or grepped.
**Pattern extraction date:** 2026-10-05
