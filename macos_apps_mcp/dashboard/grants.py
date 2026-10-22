"""Which macOS grant each adapter needs, and whether the daemon holds it (D-11).

The TCC rows come from ``deploy.grant_report()``: a read-only sqlite read, no Apple
Event and no prompt. The Health page reuses this mapping for its danger banner.
The AppleEvents target ids are the apps' bundle identifiers, confirmed from the
installed apps' Info.plist (TCC stores the controlled app's id as the row's target).
"""

from __future__ import annotations

from .. import deploy

_CAL, _REM = "kTCCServiceCalendar", "kTCCServiceReminders"
_EVENTS, _FDA = "kTCCServiceAppleEvents", "kTCCServiceSystemPolicyAllFiles"

# adapter -> ((TCC service, target bundle id | None), ...); () = needs no grant.
ADAPTER_GRANTS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "calendar": ((_CAL, None),),
    "contacts": ((_EVENTS, "com.apple.AddressBook"),),
    "mail": ((_EVENTS, "com.apple.mail"), (_FDA, None)),
    "messages": ((_EVENTS, "com.apple.MobileSMS"), (_FDA, None)),
    "music": ((_EVENTS, "com.apple.Music"),),
    "notes": ((_EVENTS, "com.apple.Notes"),),
    "photos": ((_FDA, None),),
    "reminders": ((_REM, None), (_FDA, None)),
    "safari": ((_EVENTS, "com.apple.Safari"),),
    "shortcuts": (),
}


def grant_state(
    identities: dict | None,
    adapter: str,
    client: str = deploy._BUNDLE_ID,
    *,
    complete: bool = True,
    service: str | None = None,
) -> str | None:
    """``"denied"``, ``"not asked"`` or ``"granted"`` for ``client``'s grants to
    ``adapter``; None when it cannot be told (no TCC data, or no grant needed).

    ``complete`` says both TCC databases were read: without it a missing row proves
    nothing, so it stays unknown instead of claiming "not asked". Precedence: denied,
    then not asked, then unknown, then granted. ``service`` narrows the answer to one
    TCC service (Health's ``Automation → Mail`` row is about AppleEvents only)."""
    needs = [n for n in ADAPTER_GRANTS.get(adapter, ()) if service in (None, n[0])]
    if identities is None or not needs:
        return None
    states = set()
    for service, target in needs:
        rows = [
            r
            for r in identities.get(service, [])
            if r.get("client") == client
            and (target is None or r.get("target") == target)
        ]
        # A row with a ``status`` (limited, prompt) is neither granted nor denied.
        if any(not r["granted"] and "status" not in r for r in rows):
            states.add("denied")
        elif rows and all(r["granted"] for r in rows):
            states.add("granted")
        elif rows:
            states.add("unknown")
        else:
            states.add("not asked" if complete else "unknown")
    for state in ("denied", "not asked", "unknown"):
        if state in states:
            return None if state == "unknown" else state
    return "granted"
