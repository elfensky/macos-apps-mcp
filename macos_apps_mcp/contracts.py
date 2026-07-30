"""Adapter contracts — the boundary every Apple-app adapter implements.

Settled by design (adversarial debate): **reads are uniform, writes are per-adapter
typed.**

- Query-shaped searches implement ``PointerSource``: ``get_pointers(query) ->
  list[Pointer]`` — the one shape the cockpit needs to surface *what exists* as citable
  handles. Enumeration reads (``safari_tabs``, ``messages_chats``) are per-adapter
  typed, like writes.
- Writes are **typed per-adapter methods** (``create_reminder(ReminderData)``,
  ``create_event(CalendarEventData)``) — never a stringly-typed ``create_item(dict)``,
  which rots into ``list`` vs ``list_id`` vs ``listId`` and is invisible to the type
  checker.

``Pointer`` mirrors the cockpit's citation grammar (``conventions.md``: ``[src::
system:id]`` + an open-in-app deeplink) — *pointers, not payload*: a citable handle,
never the full body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, get_args, runtime_checkable


def _to_naive_local(dt: datetime) -> datetime:
    """Canonicalize to naive **local** wall-time — the codebase's one datetime form
    (``from_nsdate`` returns naive-local, ``due_components`` reads wall-clock fields).

    An aware value is *converted* to local before the tz is dropped (never just
    stripped), so the caller's instant is preserved rather than shifted by the local
    offset. A naive value is already local by convention and passes through untouched —
    in particular it is **not** reinterpreted as UTC (parsing a date as UTC is the
    ecosystem's day-shift bug).
    """
    if dt.tzinfo is None:
        return dt
    local = dt.astimezone()
    naive = local.replace(tzinfo=None)
    # During a fall-back DST fold the wall-clock is ambiguous and ``astimezone`` leaves
    # ``fold=0``, so a later naive ``dt.timestamp()`` (via to_nsdate) would resolve to
    # the *earlier* occurrence — silently shifting the instant an hour. If the naive
    # value read back as local doesn't re-derive the original offset, it's the second
    # occurrence: set ``fold=1`` so the caller's instant survives the tz drop.
    if naive.astimezone().utcoffset() != local.utcoffset():
        naive = naive.replace(fold=1)
    return naive


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime (or date) to naive local — the canonical form (#50).

    Accepts naive ISO (``2026-06-24T09:00:00``), deliberately read as **local** time
    (not UTC — "remind me at 9" means 9 where the user is), and aware ISO (trailing
    ``Z`` or ``±HH:MM``), converted to local. A date-only string (``2026-06-24``) is
    local midnight; all-day tools snap it to a pure date downstream, so it never drifts.
    """
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(
            "expected an ISO-8601 datetime (e.g. 2026-06-24T09:00:00) or date "
            f"(2026-06-24); got {value!r}"
        ) from e
    return _to_naive_local(dt)


def parse_all_day(value: str) -> datetime:
    """Parse an all-day date param — a calendar DATE, not an instant (#50 review).

    Accepts a date-only string (2026-07-01) or a naive datetime (floored downstream).
    A timezone-aware value is REJECTED: converting an instant across timezones can
    shift the calendar day (midnight-Z parses to the previous local day west of UTC),
    and RFC 5545 forbids timezones on all-day DATE values.
    """
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(
            "expected an ISO-8601 date (e.g. 2026-07-01) or naive datetime; "
            f"got {value!r}"
        ) from e
    if dt.tzinfo is not None:
        raise ValueError(
            "all-day events take a calendar date, not a timestamp with a UTC "
            f"offset — send a date-only string like {dt.date().isoformat()!r} "
            f"(got {value!r})"
        )
    return dt


def deletion_result(ident: str, preview: Pointer | None) -> dict:
    """The ONE wire shape for every delete tool (C5d): a dry run answers
    ``{"dry_run": True, "would_delete": <pointer dict>}``; a real delete answers
    ``{"deleted": ident}``. Adapters own ``dry_run`` and build this envelope —
    tools stay one-line delegations."""
    if preview is not None:
        return {"dry_run": True, "would_delete": preview.as_dict()}
    return {"deleted": ident}


def parse_optional(label: str, value: str | None) -> datetime | None:
    """Optional ISO datetime tool-arg → naive local; empty/absent → None. A bad value
    fails at the tool boundary, labeled with the failing param (C5a — lives here with
    parse_datetime/parse_all_day so the datetime domain rules aren't smeared into the
    dispatch layer, the parse_recurrence principle)."""
    if not value:
        return None
    try:
        return parse_datetime(value)
    except ValueError as e:
        raise ValueError(f"{label}: {e}") from e


def parse_bound(label: str, value: str, *, all_day: bool) -> datetime:
    """Required event bound (start/end) tool-arg → naive local, labeled on failure.

    ``all_day=True`` parses a calendar DATE (an aware timestamp is rejected — see
    parse_all_day); otherwise an ISO datetime. Bad/empty input fails clearly at the
    tool boundary."""
    try:
        return parse_all_day(value) if all_day else parse_datetime(value)
    except ValueError as e:
        raise ValueError(f"{label}: {e}") from e


def _format_offset(offset: timedelta | None) -> str:
    """A UTC offset as ``±HH:MM`` (``+00:00`` if unknown)."""
    total = int((offset or timedelta()).total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"


def now_local(clock: datetime | None = None) -> dict:
    """Local date/time context for grounding relative dates ("tomorrow") — the model
    must not guess today from training data (#50). ``clock`` is injectable for tests.

    Returns the local ISO datetime, the plain date, the tz name, the UTC offset, and the
    weekday. All date params to the write tools are interpreted in *this* timezone.
    """
    dt = clock or datetime.now()
    # the default clock and a naive injected clock both lack a tz — attach the local
    # one so tzname/utcoffset resolve
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return {
        "datetime": dt.isoformat(timespec="seconds"),
        "date": dt.date().isoformat(),
        "timezone": dt.tzname(),
        "utc_offset": _format_offset(dt.utcoffset()),
        "weekday": dt.strftime("%A"),
    }


@dataclass(frozen=True, slots=True)
class Pointer:
    """A citable handle to one external instance — never the full body.

    ``id``       stable source id, captured at pull time (the "Connector law").
    ``summary``  short citable extract (embeddable, auditable).
    ``deeplink`` open-in-app URL, e.g. ``x-apple-reminderkit://…`` / ``ical://…``.
    """

    id: str
    summary: str
    deeplink: str
    # notes reads (notes_all, search): "Account / Folder"; create_note: the requested
    # bare folder name; None elsewhere
    folder: str | None = None
    reason: str | None = None  # triage reads only: a stable machine-readable why-string

    def as_dict(self) -> dict[str, str]:
        """The wire shape: required fields always; optional fields only when set.
        The ONE serialization of a Pointer — tool results and audit records share it."""
        d = {"id": self.id, "summary": self.summary, "deeplink": self.deeplink}
        if self.folder is not None:
            d["folder"] = self.folder
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@runtime_checkable
class PointerSource(Protocol):
    """The uniform query-search READ side: a query answered with Pointers.
    Implemented by adapters whose reads are query-shaped; enumeration reads
    (``safari_tabs``, ``messages_chats``) are per-adapter typed instead.

    Structural (``Protocol``), not an ABC — fakes satisfy it without inheritance, which
    is what keeps the tool layer unit-testable by mocking at this boundary.
    """

    def get_pointers(self, query: str) -> list[Pointer]: ...


@runtime_checkable
class Snapshotter(Protocol):
    """The by-id read an id-addressed write needs for audit before-state (#67).

    ``snapshot(ident)`` returns the current Pointer for one item, or None if the id
    no longer resolves. Declared here so AuditMiddleware consumes a contract, not a
    duck-typed method — an adapter that registers an update/delete tool with
    before-state capture must satisfy this Protocol.
    """

    def snapshot(self, ident: str) -> Pointer | None: ...


# --- disambiguation rule (#55) -------------------------------------------------------
# Name/title addressing is a READ-side affordance ONLY. A name search returns candidate
# Pointers; the model, or the user, picks one. A WRITE never auto-picks among matches:
# fuzzy/first-match auto-pick sent iMessages to the wrong human (supermemoryai #48) and
# duplicate calendar names silently mis-targeted writes (mcp-ical #16). Two results:
#   1. Every item-targeting write already takes a `Pointer.id` (complete_reminder,
#      delete_event/note, update_*) — the stable, unambiguous handle captured at read
#      time. New destructive tools MUST do the same.
#   2. The remaining name-addressed writes are CONTAINER selection only —
#      create/update_reminder(list_name) and create/update_event(calendar). Each accepts
#      EITHER a Pointer.id OR an exact name (errors.resolve_container): an id is used
#      directly (unambiguous by construction), and a name matching >1 container raises
#      errors.AmbiguousTarget LISTING the candidate ids — so the caller re-issues the
#      write with one of them, instead of macos-apps-mcp writing to the wrong container.
# The rule is STATELESS by design: there is no server-side "recent matches" store to
# resolve a later write against (carterlasalle's module-global version breaks concurrent
# sessions — a negative lesson). A write carries its own unambiguous target.
# AUDIT (#55): the only name-addressed writes are the two container params above (now
# id-or-name with candidate-listing); everything else is id-addressed, creates a fresh
# item (create_contact — no name→existing-record lookup, so nothing to disambiguate), or
# runs an OS-unique handle (run_shortcut, safari_open). Accepting both id and name (vs
# the stricter id-only form) keeps the "target a write by name" affordance while making
# an ambiguous name recoverable via the listed ids — the pre-approved #55 resolution.


# --- per-adapter typed WRITE payloads (reads uniform, writes typed) ------------------

Frequency = Literal["daily", "weekly", "monthly", "yearly"]
_FREQUENCIES: tuple[str, ...] = get_args(Frequency)
_RRULE_SUPPORTED = ("FREQ", "INTERVAL", "COUNT", "UNTIL")


def _rrule_until(v: str) -> datetime:
    """Parse an RRULE UNTIL (ISO-8601 or RFC-5545 basic), returned naive-local.

    Two corrections over a bare ``replace(tzinfo=None)``: a tz-aware value (trailing
    ``Z`` / offset) is *converted* to local before the tz is dropped, so the boundary
    names the instant the caller meant rather than shifting by the local offset; and a
    date-only UNTIL resolves to end-of-day, so "until 2026-12-31" still includes a 09:00
    occurrence on the 31st (midnight would drop it).
    """
    s = v.strip()
    parsed = None
    try:
        parsed = datetime.fromisoformat(s)  # ISO incl. trailing Z / offset on 3.11+
    except ValueError:
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
            try:
                parsed = datetime.strptime(s, fmt)
                if fmt.endswith("Z"):  # strptime parses the literal Z but stays naive
                    parsed = parsed.replace(tzinfo=UTC)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"recurrence UNTIL is not a recognizable date: {v!r}")
    # tz-aware: convert to local, then go naive — the shared canonical form (#50)
    parsed = _to_naive_local(parsed)
    if "T" not in s.upper():  # date-only → include the whole final day
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
    return parsed


@dataclass(frozen=True, slots=True)
class Recurrence:
    """A repeat rule — the FREQ/INTERVAL/COUNT/UNTIL subset of RFC 5545.

    Pure data: the EventKit ``EKRecurrenceRule`` mapping lives in
    ``runtime.to_recurrence_rule``, so this module stays free of native imports.
    """

    frequency: Frequency
    interval: int = 1  # every N periods
    count: int | None = None  # end after N occurrences …
    until: datetime | None = None  # … or end on a date (mutually exclusive with count)

    def __post_init__(self) -> None:
        # Enforce the documented invariant on the contract itself, so it holds however
        # a Recurrence is built (direct construction included), not only via from_rrule.
        if self.count is not None and self.until is not None:
            raise ValueError("recurrence count and until are mutually exclusive")

    @classmethod
    def from_rrule(cls, rrule: str) -> Recurrence:
        """Parse an RFC 5545 RRULE (the supported subset).

        e.g. ``FREQ=WEEKLY;INTERVAL=2;COUNT=10``. FREQ is required; COUNT and UNTIL are
        mutually exclusive. Unsupported parts (BYDAY, BYMONTHDAY, …) are rejected so a
        rule never silently does the wrong thing.
        """
        body = rrule.strip()
        if body.upper().startswith("RRULE:"):
            body = body[6:]
        fields: dict[str, str] = {}
        for token in body.split(";"):
            token = token.strip()
            if not token:
                continue
            if "=" not in token:
                raise ValueError(f"bad RRULE part {token!r} (expected KEY=VALUE)")
            key, _, val = token.partition("=")
            fields[key.strip().upper()] = val.strip()

        extra = set(fields) - set(_RRULE_SUPPORTED)
        if extra:
            raise ValueError(
                f"unsupported RRULE part(s): {', '.join(sorted(extra))} "
                f"(supported: {', '.join(_RRULE_SUPPORTED)})"
            )
        freq = fields.get("FREQ", "").lower()
        if freq not in _FREQUENCIES:
            raise ValueError(
                f"RRULE FREQ must be one of {_FREQUENCIES}; got {fields.get('FREQ')!r}"
            )
        interval = int(fields["INTERVAL"]) if "INTERVAL" in fields else 1
        if interval < 1:
            raise ValueError(f"RRULE INTERVAL must be >= 1; got {interval}")
        if "COUNT" in fields and "UNTIL" in fields:
            raise ValueError("RRULE COUNT and UNTIL are mutually exclusive")
        count = int(fields["COUNT"]) if "COUNT" in fields else None
        if count is not None and count < 1:
            raise ValueError(f"RRULE COUNT must be >= 1; got {count}")
        until = _rrule_until(fields["UNTIL"]) if "UNTIL" in fields else None
        return cls(frequency=freq, interval=interval, count=count, until=until)


class _ClearRecurrence:
    """Sentinel: explicitly stop a reminder repeating (recurrence='none')."""


CLEAR_RECURRENCE = _ClearRecurrence()


def parse_recurrence(rrule: str | None) -> Recurrence | None:
    """Tool-arg parse: optional RFC-5545 RRULE string → Recurrence. Empty/absent/'none'
    → None. Lives here with the other tool-arg parsers (parse_datetime/parse_all_day)
    so the recurrence domain rule isn't smeared into the dispatch layer."""
    if not rrule or rrule.strip().lower() == "none":
        return None  # 'none' is taught by update_reminder — accept it everywhere
    return Recurrence.from_rrule(rrule)


def parse_recurrence_update(rrule: str | None) -> Recurrence | _ClearRecurrence | None:
    """update_reminder's tri-state recurrence: absent/empty → None (unspecified —
    refused downstream when the target repeats); the literal 'none' →
    CLEAR_RECURRENCE (explicit stop); anything else parses as an RRULE."""
    if not rrule:
        return None
    if rrule.strip().lower() == "none":
        return CLEAR_RECURRENCE
    return Recurrence.from_rrule(rrule)


@dataclass(frozen=True, slots=True)
class ReminderData:
    """Payload for creating/updating an Apple Reminder."""

    title: str
    due: datetime | None = None
    list_name: str | None = None
    notes: str | None = None
    priority: int = 0  # 0 none, 1–9 (1 highest); enforced in __post_init__
    start: datetime | None = None  # start date, distinct from due (None clears)
    # repeat rule: None = unspecified (an update REFUSES on a repeating target),
    # CLEAR_RECURRENCE = explicit stop, Recurrence = set/replace the rule
    recurrence: Recurrence | _ClearRecurrence | None = None

    def __post_init__(self) -> None:
        # EventKit rejects a repeating reminder with no due date (EKError 18) — surface
        # it at the boundary as a clear ValueError, not a deep native save failure.
        if isinstance(self.recurrence, Recurrence) and self.due is None:
            raise ValueError("a recurring reminder needs a due date")
        # EventKit priority is 0 (none) or 1–9 (1 highest); enforce on the contract so
        # the invariant holds however ReminderData is built, not only via the MCP tool.
        if not 0 <= self.priority <= 9:
            raise ValueError(
                f"reminder priority must be 0–9 (0=none); got {self.priority}"
            )


@dataclass(frozen=True, slots=True)
class CalendarEventData:
    """Payload for creating/updating an Apple Calendar event."""

    title: str
    start: datetime
    end: datetime
    calendar: str | None = None
    location: str | None = None
    notes: str | None = None
    all_day: bool = False
    # repeat rule; None leaves an existing series rule untouched (unlike the reminder
    # case, an event can't be safely un-recurred through the occurrence-edit path —
    # delete the series instead). See calendar._apply_event.
    recurrence: Recurrence | None = None


@dataclass(frozen=True, slots=True)
class ContactData:
    """Payload for creating an Apple Contact (name + org; v1 keeps it minimal)."""

    given_name: str
    family_name: str | None = None
    organization: str | None = None


@dataclass(frozen=True, slots=True)
class NoteData:
    """Payload for creating/updating an Apple Note (plaintext title + body)."""

    title: str
    body: str = ""
    folder: str | None = None  # None → default folder; else an existing folder name
