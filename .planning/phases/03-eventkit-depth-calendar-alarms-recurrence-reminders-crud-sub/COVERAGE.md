# API Coverage — EventKit (Calendar and Reminders) and the Reminders sqlite store

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

Phase 3 widens the existing EventKit integration (PyObjC, macOS 27). Google Calendar is
reached only through EventKit's CalDAV source, never through the Google Calendar API; the
"Google Calendar API" in D-01 names only the minutes-before convention. The rows cover the
EventKit surface this phase's requirements touch, and the neighbouring capabilities a
caller could expect.

| capability | decision | reason |
|---|---|---|
| event-alarms-relative (EKAlarm relativeOffset on create/update) | INTEGRATE | |
| event-alarms-absolute (EKAlarm absoluteDate) | OPT-OUT | explicitly out of scope (D-01): Google rewrites it after the save, and it fires on the wrong day of a floating all-day event |
| event-alarms-location-proximity (structuredLocation, proximity) | OPT-OUT | not needed — no requirement asks for geofenced alerts |
| reminder-alarms | OPT-OUT | explicitly out of scope — REM-05 is a v2 requirement |
| recurrence-freq-interval-count-until | INTEGRATE | |
| recurrence-byday-ordinals | INTEGRATE | |
| recurrence-bymonthday | INTEGRATE | |
| recurrence-bymonth | INTEGRATE | |
| recurrence-byyearday | INTEGRATE | |
| recurrence-bysetpos | INTEGRATE | |
| recurrence-byweekno | OPT-OUT | EventKit saves it but expands only DTSTART (spike 003); refused by name |
| recurrence-byhour-byminute-bysecond-wkst | OPT-OUT | EventKit has no field for them; refused by name (D-06) |
| recurrence-multiple-rules-per-item | OPT-OUT | not needed — every tool takes one RRULE, and verify compares the first rule |
| recurrence-on-reminders (shared parser, D-11) | INTEGRATE | |
| event-delete-with-gone-check | INTEGRATE | |
| reminder-delete | INTEGRATE | |
| reminder-list-create (saveCalendar, reminder entity) | INTEGRATE | |
| reminder-list-rename-delete | OPT-OUT | not needed yet — REM-02 and #92 ask for create only; a list delete removes every reminder in it and needs its own recoverable design |
| event-calendar-create-delete | OPT-OUT | not needed — no requirement; Google refuses new calendars (EKErrorDomain 17) |
| container-id-on-pointers (calendarIdentifier) | INTEGRATE | |
| reminder-tags-read (Reminders sqlite store) | INTEGRATE | |
| reminder-subtasks-read (Reminders sqlite store, ZPARENTREMINDER) | INTEGRATE | |
| reminder-tags-and-subtasks-write | OPT-OUT | explicitly out of scope — no public API exists (spike 002); private parentID/setParentID: is forbidden (REM-04) |
| event-attendees-organizer | OPT-OUT | not needed — no requirement in this milestone |
| event-structured-location-url-availability-write | OPT-OUT | not needed — no requirement in this milestone |
| event-time-zone-override | OPT-OUT | not needed — all-day events stay floating (D-05); timed events keep naive local |
