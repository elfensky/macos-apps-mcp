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

import re
from calendar import isleap, monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


def read_result(
    results,
    *,
    cap: int | None = None,
    plane: str | None = None,
    coverage: str | None = None,
    staleness: str | None = None,
) -> dict:
    """The ONE wire shape for a BOUNDED read (#156): ``{results, truncated?, plane?,
    coverage?}``. Lives here next to ``deletion_result`` for the same reason — "what
    does a successful call MEAN" is one contracts fact with one test, not ten tool-level
    behaviours that drift.

    The defect it closes: a read that succeeds while under-answering, with nothing in
    the payload to say so. For a caller whose job is to tell a human what they missed, a
    false negative that reads as authoritative is the worst available failure mode —
    worse than an error, which at least prompts a retry.

    Every optional field is **emitted only when set**, like ``Pointer.folder``, and the
    absences are meaningful because every bounded read uses this one helper:

    - ``truncated``  present (True) when the read came back exactly AT its cap, so there
      may be more. Absent means the answer is complete. Deliberately conservative: a set
      that happens to be exactly ``cap`` long is reported as possibly-truncated rather
      than possibly-lying.
    - ``plane``  present only when a read did NOT use its documented plane — today only
      ``mail_search``'s AppleScript inbox fallback, which is shaped identically to a
      whole-store result but scanned one mailbox. Absent means the documented plane.
    - ``coverage``  present when an empty/short answer is explained by an index that
      does not cover the whole store, so "no matches" is not mistaken for "nothing
      exists".
    - ``staleness``  present when the store the read answered from is known to LAG
      the truth (#201: a Message-ID sidecar whose harvest is behind Mail's index) —
      the answer stands, but recent items may be missing and the note names the
      catch-up action.

    Pointers are serialized through ``as_dict`` here, so a tool stays a one-line
    delegation and the adapter keeps deciding what it actually answered.
    """
    rows = [r.as_dict() if isinstance(r, Pointer) else r for r in results]
    out: dict = {"results": rows}
    if cap is not None and len(rows) >= cap:
        out["truncated"] = True
    if plane is not None:
        out["plane"] = plane
    if coverage is not None:
        out["coverage"] = coverage
    if staleness is not None:
        out["staleness"] = staleness
    return out


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
    # bare folder name; mail reads: the round-trip mailbox token; events/reminders
    # reads: the owning calendar or list identifier — the token free_busy(calendars=…),
    # create_event(calendar=…) and create_reminder(list_name=…) take (#207); unset for
    # reads that have no container
    folder: str | None = None
    reason: str | None = None  # triage reads only: a stable machine-readable why-string
    # mail reads: the owning account's id — the uuid segment of ``folder``'s url, so it
    # costs no extra query and no Mail launch (#155). Deliberately UNSET, never guessed,
    # on the reads that go through Mail's unified cross-account accessors: there the
    # account genuinely is unknown. ``mail_overview`` maps it to a display name.
    account: str | None = None
    # mail_thread(snippets=True) only: a bounded first-extract of the body, read at rest
    # (#158). It stays optional and opt-in because a snippet on every pointer of a
    # 100-message thread is the payload dump "pointers, not payload" exists to prevent.
    snippet: str | None = None

    def as_dict(self) -> dict[str, str]:
        """The wire shape: required fields always; optional fields only when set.
        The ONE serialization of a Pointer — tool results and audit records share it."""
        d = {"id": self.id, "summary": self.summary, "deeplink": self.deeplink}
        if self.folder is not None:
            d["folder"] = self.folder
        if self.reason is not None:
            d["reason"] = self.reason
        if self.account is not None:
            d["account"] = self.account
        if self.snippet is not None:
            d["snippet"] = self.snippet
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
_RRULE_SUPPORTED = (
    "FREQ",
    "INTERVAL",
    "COUNT",
    "UNTIL",
    "BYDAY",
    "BYMONTHDAY",
    "BYMONTH",
    "BYYEARDAY",
    "BYSETPOS",
)
# Parts refused by name (D-06). BYWEEKNO is the trap: EventKit saves it without error
# and then expands only DTSTART, so a "supported" BYWEEKNO would be a silent wrong rule.
_RRULE_REJECTED = {
    "BYWEEKNO": "EventKit saves it but expands only the first occurrence (spike 003)",
    "BYHOUR": "EventKit has no field for it",
    "BYMINUTE": "EventKit has no field for it",
    "BYSECOND": "EventKit has no field for it",
    "WKST": "EventKit has no field for it",
}
_WEEKDAY_CODES = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")
_BYDAY_ITEM = re.compile(r"^([+-]?\d+)?([A-Za-z]{2})$")


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


def _parse_byday(value: str) -> tuple[tuple[int, str], ...]:
    """BYDAY list → ``(ordinal, code)`` pairs; ordinal 0 for a plain weekday."""
    days = []
    for item in value.split(","):
        m = _BYDAY_ITEM.match(item.strip())
        if m is None or m.group(2).upper() not in _WEEKDAY_CODES:
            raise ValueError(
                f"RRULE BYDAY item {item.strip()!r} is not a weekday "
                f"({', '.join(_WEEKDAY_CODES)}) with an optional ordinal such as 2TU"
            )
        ordinal = int(m.group(1) or 0)
        if m.group(1) and ordinal == 0:  # "0MO" is not "every MO" — say so
            raise ValueError(
                f"RRULE BYDAY ordinal 0 in {item.strip()!r} is out of range "
                "(omit the ordinal for every such weekday)"
            )
        days.append((ordinal, m.group(2).upper()))
    return tuple(days)


def _by_ints(fields: dict[str, str], part: str) -> tuple[int, ...]:
    return _parse_ints(part, fields[part]) if part in fields else ()


def _parse_ints(part: str, value: str) -> tuple[int, ...]:
    """Comma list of signed integers for a BY part; range checks are the dataclass's."""
    out = []
    for item in value.split(","):
        try:
            out.append(int(item.strip()))
        except ValueError:
            raise ValueError(
                f"RRULE {part} item {item.strip()!r} is not an integer"
            ) from None
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Recurrence:
    """A repeat rule — the FREQ/INTERVAL/COUNT/UNTIL/BY* subset of RFC 5545.

    Pure data: the EventKit ``EKRecurrenceRule`` mapping lives in
    ``eventkit.to_recurrence_rule``, so this module stays free of native imports.
    ``byday`` holds sorted unique ``(ordinal, code)`` pairs (ordinal 0 = every such
    weekday); the other BY parts are sorted unique ints. All default to ``()``.
    """

    frequency: Frequency
    interval: int = 1  # every N periods
    count: int | None = None  # end after N occurrences …
    until: datetime | None = None  # … or end on a date (mutually exclusive with count)
    byday: tuple[tuple[int, str], ...] = ()
    bymonthday: tuple[int, ...] = ()
    bymonth: tuple[int, ...] = ()
    byyearday: tuple[int, ...] = ()
    bysetpos: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        # Enforce the documented invariant on the contract itself, so it holds however
        # a Recurrence is built (direct construction included), not only via from_rrule.
        if self.count is not None and self.until is not None:
            raise ValueError("recurrence count and until are mutually exclusive")
        # canonical form: sorted unique, so equal rules compare equal however built
        for name in ("byday", "bymonthday", "bymonth", "byyearday", "bysetpos"):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))
        self._validate_by_parts()

    def _validate_by_parts(self) -> None:
        """Ranges and RFC 5545 §3.3.10 combination bans. EventKit validates none of
        this and saves a nonsense rule without error (RESEARCH Pitfall 3), so the
        boundary does — on direct construction too."""
        for name, limit in (("bymonthday", 31), ("byyearday", 366), ("bysetpos", 366)):
            for v in getattr(self, name):
                if v == 0 or abs(v) > limit:
                    raise ValueError(
                        f"{name.upper()} value {v} is out of range "
                        f"(±1 to ±{limit}; 0 is not allowed)"
                    )
        for v in self.bymonth:
            if not 1 <= v <= 12:
                raise ValueError(f"BYMONTH value {v} is out of range (1 to 12)")
        for ordinal, code in self.byday:
            if code not in _WEEKDAY_CODES:
                codes = ", ".join(_WEEKDAY_CODES)
                raise ValueError(f"BYDAY code {code!r} is not a weekday ({codes})")
            if abs(ordinal) > 53:
                raise ValueError(f"BYDAY ordinal {ordinal} is out of range (±1 to ±53)")
        freq = self.frequency.upper()
        ordinals = [n for n, _ in self.byday if n]
        if ordinals and self.frequency not in ("monthly", "yearly"):
            raise ValueError(
                "BYDAY with an ordinal such as 2TU is only valid with FREQ=MONTHLY "
                f"or FREQ=YEARLY, not FREQ={freq} (RFC 5545)"
            )
        # a month has at most five of any weekday: a bigger ordinal saves a rule that
        # never fires (Pitfall 3 warning sign). A YEARLY ordinal is per month only
        # when BYMONTH narrows it.
        if self.frequency == "monthly" or (self.frequency == "yearly" and self.bymonth):
            for n in ordinals:
                if abs(n) > 5:
                    raise ValueError(
                        f"BYDAY ordinal {n} is out of range for a month (±1 to ±5): "
                        "a month has at most five of any weekday"
                    )
        if self.bymonthday and self.frequency == "weekly":
            raise ValueError("BYMONTHDAY must not be used with FREQ=WEEKLY (RFC 5545)")
        if self.byyearday and self.frequency in ("daily", "weekly", "monthly"):
            raise ValueError(f"BYYEARDAY must not be used with FREQ={freq} (RFC 5545)")
        if self.bysetpos and not (
            self.byday or self.bymonthday or self.bymonth or self.byyearday
        ):
            raise ValueError(
                "BYSETPOS must be used with another BY part such as BYDAY (RFC 5545)"
            )

    @classmethod
    def from_rrule(cls, rrule: str) -> Recurrence:
        """Parse an RFC 5545 RRULE (the supported subset).

        e.g. ``FREQ=MONTHLY;INTERVAL=2;BYDAY=2TU;COUNT=10``. FREQ is required; COUNT and
        UNTIL are mutually exclusive. Supported: FREQ, INTERVAL, COUNT, UNTIL, BYDAY
        (with ordinals such as 2TU, -1FR), BYMONTHDAY, BYMONTH, BYYEARDAY, BYSETPOS.
        BYWEEKNO, BYHOUR, BYMINUTE, BYSECOND and WKST are refused *by name* (BYWEEKNO is
        the trap: EventKit saves it and expands only DTSTART). EventKit validates no BY
        value, so ranges and the RFC 5545 combination bans are checked here, before any
        native call (RESEARCH Pitfall 3), so a rule never silently does the wrong thing.
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

        for part in sorted(set(fields) & set(_RRULE_REJECTED)):
            raise ValueError(
                f"unsupported RRULE part {part}: {_RRULE_REJECTED[part]}; "
                f"supported: {', '.join(_RRULE_SUPPORTED)}"
            )
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
        return cls(
            frequency=freq,
            interval=interval,
            count=count,
            until=until,
            byday=_parse_byday(fields["BYDAY"]) if "BYDAY" in fields else (),
            bymonthday=_by_ints(fields, "BYMONTHDAY"),
            bymonth=_by_ints(fields, "BYMONTH"),
            byyearday=_by_ints(fields, "BYYEARDAY"),
            bysetpos=_by_ints(fields, "BYSETPOS"),
        )


def _is_nth(n: int, size: int, wanted: tuple[int, ...]) -> bool:
    """``n`` (1-based) or its from-the-end form (``n - size - 1``) is in ``wanted``."""
    return n in wanted or n - size - 1 in wanted


def _passes_by_filters(rule: Recurrence, d: date) -> bool:
    """Whether ``d`` survives every BY filter of ``rule`` (BYSETPOS aside)."""
    if rule.bymonth and d.month not in rule.bymonth:
        return False
    year_size = 366 if isleap(d.year) else 365
    yday = d.timetuple().tm_yday
    if rule.byyearday and not _is_nth(yday, year_size, rule.byyearday):
        return False
    month_size = monthrange(d.year, d.month)[1]
    if rule.bymonthday and not _is_nth(d.day, month_size, rule.bymonthday):
        return False
    if not rule.byday:
        return True
    code = _WEEKDAY_CODES[(d.weekday() + 1) % 7]  # _WEEKDAY_CODES starts on Sunday
    # an ordinal counts inside the month for MONTHLY and YEARLY+BYMONTH, else the year
    in_month = rule.frequency == "monthly" or (
        rule.frequency == "yearly" and bool(rule.bymonth)
    )
    pos, size = (d.day, month_size) if in_month else (yday, year_size)
    nth = (pos - 1) // 7 + 1
    from_end = -((size - pos) // 7 + 1)
    return any(
        wd == code and ordinal in (0, nth, from_end) for ordinal, wd in rule.byday
    )


def _period(frequency: str, d: date) -> tuple[date, date]:
    """The half-open ``[lo, hi)`` date range BYSETPOS counts inside."""
    if frequency == "daily":
        return d, d + timedelta(days=1)
    if frequency == "weekly":
        lo = d - timedelta(days=d.weekday())
        return lo, lo + timedelta(days=7)
    if frequency == "monthly":
        lo = d.replace(day=1)
        return lo, (lo + timedelta(days=32)).replace(day=1)
    return date(d.year, 1, 1), date(d.year + 1, 1, 1)


def dtstart_in_rule(rule: Recurrence, start: date) -> bool:
    """Whether ``start`` itself is one of the dates ``rule`` describes (D-10).

    RFC 5545 §3.3.10 counts DTSTART as the first instance even when it does not match
    the rule, and EventKit agrees, so this check only decides whether that first
    occurrence is *extra*. Pure stdlib over the supported parts: an absent part is
    implied by DTSTART and never fails; INTERVAL, COUNT and UNTIL do not affect
    membership. BYSETPOS picks from the candidates of ``start``'s own period — the
    month, the year, or the Monday-to-Sunday week (RFC default WKST=MO; EventKit reads
    2 for ``firstDayOfTheWeek``).

    python-dateutil is not used: it drops a non-matching DTSTART and diverges from RFC
    5545 on mixed plain/ordinal BYDAY and on WEEKLY+BYSETPOS.
    """
    d = date(start.year, start.month, start.day)  # a datetime is accepted too
    if not _passes_by_filters(rule, d):
        return False
    if not rule.bysetpos:
        return True
    lo, hi = _period(rule.frequency, d)
    candidates = [
        x
        for x in (lo + timedelta(days=i) for i in range((hi - lo).days))
        if _passes_by_filters(rule, x)
    ]
    position = candidates.index(d) + 1
    return _is_nth(position, len(candidates), rule.bysetpos)


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
    # alarms, as minutes BEFORE the start (the Google Calendar API convention). None =
    # leave the event's alarms untouched, () = clear them, (15, 60) = exactly those.
    alarms: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if self.alarms is not None and len(self.alarms) > 5:
            raise ValueError(
                "at most 5 alarms: Google keeps 5 and silently drops a different one "
                "after the save"
            )


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
