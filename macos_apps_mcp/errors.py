"""Typed error taxonomy + pure write-policy helpers (#47) — no native imports.

The winnable axis is trust: the category leader died of *fake success* — stubbed reads
returning [] made permission-denied / crashed / genuinely-empty indistinguishable, so
the agent hammered a denied tool. Every native failure is one of these loud, typed
classes; str(e) IS the agent-directed remediation. The dispatch layer (server.py)
turns them into MCP tool *results* carrying that directive — never a silent [], never
a masked stack trace. ``kind`` is the machine code doctor (#48) and tests branch on.

Pure by design: nothing here touches EventKit/PyObjC/Foundation, so the taxonomy and
the write policies (``resolve_container``, ``verify_persisted``, …) unit-test with
plain values and can be imported anywhere — text.py, adapters, tests — without loading
the native worker in runtime.py.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

# The one Settings pane every TCC remediation points at. Shared by the error
# directives here and in runtime.py and by doctor's report lines (#48), so the
# wording can never drift between the raise sites and the diagnosis.
PRIVACY_PANE = "System Settings → Privacy & Security"


class NativeError(RuntimeError):
    """Base for every typed native failure. ``str(e)`` is the agent-facing directive."""

    kind = "native_error"


class AccessDenied(NativeError):
    """Calendar/Reminders (EventKit) TCC access is not fully granted."""

    kind = "access_denied"


class AutomationDenied(NativeError):
    """osascript blocked from controlling an app — Automation consent not granted."""

    kind = "automation_denied"


class AppNotRunning(NativeError):
    """The target app isn't running / its Apple-events connection is invalid."""

    kind = "app_not_running"


class NativeTimeout(NativeError):
    """A native call didn't return in time (stuck dialog, pathological query)."""

    kind = "native_timeout"


class OutputOverflow(NativeError):
    """A native result exceeded the caller's size cap (raised by callers, e.g. #52)."""

    kind = "output_overflow"


class SchemaDrift(NativeError):
    """Native output didn't match the shape the parser expects (an OS/app change)."""

    kind = "schema_drift"


class VerificationFailed(NativeError):
    """A create/update didn't persist as requested — the returned id is fabricated, or
    a field was dropped, or iCloud reverted the write (#49)."""

    kind = "verification_failed"


class SpanRequired(NativeError):
    """A recurring event's update/delete needs an explicit span (this-event vs
    future-events) so one occurrence isn't silently rewritten as the series (#51)."""

    kind = "span_required"


class WriteRefused(NativeError):
    """The store refused a save/remove — a read-only or subscribed calendar/list, or
    the account rejected the change."""

    kind = "write_refused"


class RecurrenceRequired(NativeError):
    """Updating a repeating reminder needs an explicit recurrence (re-send the rule
    or 'none') so a rename can't silently destroy the series (mirror of
    SpanRequired's rationale, #51)."""

    kind = "recurrence_required"


class BatchTooLarge(NativeError):
    """A bulk operation exceeded its small default safety cap without an explicit
    override — contains blast radius (griches --confirm-destructive, #54)."""

    kind = "batch_too_large"


class AmbiguousTarget(NativeError):
    """A name/title matched more than one container, so a write cannot safely pick one
    — disambiguation rule (#55): see contracts.py. ``str(e)`` tells the caller how to
    disambiguate."""

    kind = "ambiguous_target"


class FullDiskAccessDenied(NativeError):
    """A native sqlite store (chat.db, NoteStore.sqlite, …) couldn't be opened because
    Full Disk Access is not granted. ``str(e)`` is the remediation; doctor (#48) reports
    the same surface. Part of the dual-backend policy (#58): the adapter falls back to
    its AppleScript reader if it has one (Notes), else this surfaces loudly — never a
    silent empty (Messages content)."""

    kind = "full_disk_access_denied"


def resolve_container(items: list[tuple[str, str, T]], target: str, *, noun: str) -> T:
    """Resolve a write's container target by ``Pointer.id`` (exact) OR exact name.

    Disambiguation rule (#55): see contracts.py. ``items`` is ``list[(id, name,
    value)]``; the matched ``value`` (the native container object) is returned.
    id-first (a container id is a UUID, so it can't collide with a human-typed name);
    0 name matches → ``ValueError``; >1 → ``AmbiguousTarget`` listing the candidate
    ids. Pure (no native imports) so it unit-tests with plain tuples.
    """
    for cid, _name, value in items:
        if cid == target:  # id-first: an unambiguous handle is used directly
            return value
    matches = [(cid, value) for cid, name, value in items if name == target]
    if not matches:
        raise ValueError(f"no {noun} named {target!r}")
    if len(matches) > 1:
        ids = ", ".join(cid for cid, _ in matches)
        raise AmbiguousTarget(
            f"{len(matches)} {noun}s are named {target!r} — macos-apps-mcp never "
            "auto-picks an ambiguous write target. Re-issue the write targeting one of "
            f"these ids instead: {ids} (or rename them so the names are unique)."
        )
    return matches[0][1]


def refused_write(what: str, noun: str, err: object) -> WriteRefused:
    """The uniform store-refused-a-save error: ONE wording for every EventKit write
    (create/update/delete/complete), instead of six hand-typed copies. ``what`` names
    the operation ("event write", "reminder completion"); ``noun`` the container kind
    ("calendar", "list"). Returned, not raised, so the call site reads ``raise
    refused_write(...)``."""
    return WriteRefused(
        f"the {what} was refused by the store: {err}. The target {noun} may be "
        f"read-only (a subscribed {noun}) or the account rejected the change — do "
        "not retry the same target; tell the user."
    )


def verify_persisted(
    entity: str, expected: dict[str, object], actual: dict[str, object]
) -> None:
    """Diff requested field values against what the store actually persisted; raise
    ``VerificationFailed`` naming every dropped/changed field (#49).

    The anti-fabrication + anti-rollback check behind every create/update: the category
    leader shipped a fabricated id and dropped due/list (supermemoryai #64), and iCloud
    can revert a write ~1s later — and our writes feed the vault id-writeback, so a fake
    or reverted id silently corrupts the cockpit. Callers pass primitives already
    normalized for comparison (dates → epoch ints / y-m-d tuples, containers → names) so
    this stays pure and unit-testable with plain fakes.
    """
    dropped = {k: (v, actual.get(k)) for k, v in expected.items() if actual.get(k) != v}
    if dropped:
        fields = "; ".join(
            f"{k}: requested {req!r}, persisted {got!r}"
            for k, (req, got) in dropped.items()
        )
        raise VerificationFailed(
            f"{entity} write did not persist as requested (dropped or reverted; iCloud "
            f"can roll a write back ~1s later). Mismatches: {fields}. Re-read the item "
            "before trusting it; do not reuse the returned id."
        )


def require_batch_within(count: int, cap: int, *, override_param: str) -> None:
    """Guard a bulk operation's size (#54): raise ``BatchTooLarge`` when ``count``
    exceeds the small default ``cap``, naming the ``override_param`` the caller can pass
    to raise the cap deliberately. Small caps + explicit override contain blast radius
    (griches). The first bulk destructive op wires this in; single-item writes don't
    need it. ponytail: this is the shared primitive — a bulk op calls it, it does not
    invent its own limit check."""
    if count > cap:
        raise BatchTooLarge(
            f"this operation would affect {count} items but the safety cap is {cap}. "
            f"Narrow the batch, or pass {override_param}=<n> to raise the cap on "
            "purpose. Do not retry the same oversized batch unchanged."
        )
