"""The Health and Backups pages (PLAT-02, D-13, D-14, RESEARCH C7).

Same harness as the other dashboard tests: ``tests/_dashboard.py`` builds the app with
the test page key and sends its cookie; there is no socket. ``doctor.diagnose`` and
``deploy.grant_report`` are faked at the seam, so no test reads the real TCC database,
sends an Apple Event or starts an EventKit request. Every fixture is invented and
written under a private ``XDG_STATE_HOME``.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time

import pytest

from macos_apps_mcp import deploy, doctor, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from macos_apps_mcp.dashboard import grants, health
from tests._dashboard import get

BUNDLE = deploy._BUNDLE_ID
BOTH_READ = {"user": None, "system": None}


def _identity(service, target=None, granted=True):
    row = {"client": BUNDLE, "granted": granted}
    if target:
        row["target"] = target
    return service, row


def make_ids(*, fda=True, skip=("music",), denied=()):
    """A TCC identity map for ``BUNDLE``: every Automation target granted except the
    adapters in ``skip`` (no row at all), Calendar and Reminders granted, the Full Disk
    Access row ``fda``. ``denied`` names adapters whose AppleEvents row is denied."""
    ids: dict[str, list[dict]] = {}
    pairs = [
        ("kTCCServiceCalendar", None, True),
        ("kTCCServiceReminders", None, True),
        ("kTCCServiceSystemPolicyAllFiles", None, fda),
    ]
    for adapter, needs in grants.ADAPTER_GRANTS.items():
        for service, target in needs:
            if target and adapter not in skip:
                pairs.append((service, target, adapter not in denied))
    for service, target, granted in pairs:
        s, row = _identity(service, target, granted)
        ids.setdefault(s, []).append(row)
    return ids


def make_report(ids="default", **surface_overrides):
    ids = make_ids() if ids == "default" else ids
    surfaces = {
        "calendar": ("eventkit", True, "full_access"),
        "reminders": ("eventkit", True, "full_access"),
        "full_disk_access": ("fda", True, "ok"),
    }
    surfaces.update(surface_overrides)
    return {
        "version": "0.15.0",
        "build": "abc1234 2026-10-21T10:00:00Z",
        "summary": "no denied surfaces; Automation unprobed",
        "surfaces": [
            {"surface": n, "kind": k, "ok": ok, "status": st}
            for n, (k, ok, st) in surfaces.items()
        ],
        "deployment": {
            "mode": "daemon",
            "agent": "enabled",
            "grant_identities": ids,
            "mail_backups": "3.4 MB in 12 receipts (oldest 20260801), kept forever",
            "note": "grants listed per identity",
        },
    }


class Doc:
    """The fake ``doctor.diagnose``: records its calls, can block on ``gate``."""

    def __init__(self):
        self.calls: list = []
        self.report = make_report()
        self.reasons = dict(BOTH_READ)
        self.gate: threading.Event | None = None

    def diagnose(self, request=False):
        self.calls.append(request)
        if self.gate is not None:
            assert self.gate.wait(10), "the test never released the fake"
        return self.report

    def grant_report(self):
        return {
            "identities": self.report["deployment"]["grant_identities"],
            "reasons": self.reasons,
        }


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """A private state dir and a fresh single-flight lock; the daemon role."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.setattr(health, "_lock", threading.Lock())
    monkeypatch.setattr(health, "_last", None)
    monkeypatch.setattr(health, "_dot", None)
    return tmp_path


@pytest.fixture
def doc(monkeypatch):
    d = Doc()
    monkeypatch.setattr(doctor, "diagnose", d.diagnose)
    monkeypatch.setattr(deploy, "grant_report", d.grant_report)
    return d


def titles(text):
    return re.findall(r'<div class="title">(.*?)</div>', text)


def sub_of(text, title):
    m = re.search(
        rf'<div class="title">{re.escape(title)}</div><div class="sub">(.*?)</div>',
        text,
        re.S,
    )
    return html.unescape(m.group(1)) if m else None


def value_of(text, title):
    m = re.search(
        rf'<div class="title">{re.escape(title)}</div></div>'
        r'<span class="muted">(.*?)</span>',
        text,
        re.S,
    )
    return html.unescape(m.group(1)) if m else None


# --- Health: the doctor report (D-14) ---------------------------------------------


def test_health_shows_what_doctor_reports(doc):
    doc.report["summary"] = "<script>alert(1)</script>"
    r = get("/health")
    assert r.status_code == 200
    text = r.text
    assert "<h1>Health</h1>" in text
    assert 'What <span class="mono">doctor</span> reports right now.' in text
    for t in ("Daemon", "Adapters", "Full Disk Access", "EventKit", "Outbound"):
        assert f'<div class="title">{t}</div>' in text
    assert "Mail backups" in titles(text)
    assert sub_of(text, "Mail backups").startswith("3.4 MB in 12 receipts")
    assert "Deployment" in text
    assert value_of(text, "Version") == "0.15.0 · built abc1234 2026-10-21T10:00:00Z"
    assert re.fullmatch(r"daemon, pid \d+, up .+", value_of(text, "Mode"))
    assert value_of(text, "Listens on") == "127.0.0.1:47632 (loopback only)"
    assert value_of(text, "Grant identity") == BUNDLE
    # the full report is escaped JSON inside <details>
    m = re.search(
        r"<details[^>]*><summary>Full doctor report</summary>"
        r'<pre class="json">(.*?)</pre></details>',
        text,
        re.S,
    )
    assert m and json.loads(html.unescape(m.group(1))) == doc.report
    assert "<script>alert(1)" not in text and "&lt;script&gt;" in text
    assert doc.calls == [False]  # request=False only: no consent prompt, ever


def test_health_outbound_row_is_locked_text_with_the_command(doc):
    text = get("/health").text
    sending = registry.outbound_status()["registered"]
    command = "macos-apps-mcp allow-send " + ("off" if sending else "mail")
    assert f"<code>{command}</code>" in text and f'data-copy="{command}"' in text
    assert sub_of(text, "Outbound").startswith(
        f"Send enabled for: {', '.join(sending)}" if sending else "Send off"
    )
    # no form, no input for the gate: the page has none besides the sidebar's links
    assert "<form" not in text and "<input" not in text


def test_health_adapters_row_counts_pending_changes(doc, monkeypatch):
    names = sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": names, "configured": names[:-2]},
    )
    text = get("/health").text
    sub = sub_of(text, "Adapters")
    assert sub.startswith(f"{len(names)} active: ") and sub.endswith(
        "— 2 pending restart"
    )
    assert re.search(r'<a class="btn" href="/adapters">Show</a>', text)


# --- Health: single flight, off the loop (RESEARCH C7) ----------------------------


def test_health_busy_and_single_flight(doc, monkeypatch):
    monkeypatch.setattr(health, "_WAIT", 0.2)
    doc.gate = threading.Event()
    try:
        first = get("/health")  # the fake blocks; the wait bound ends the request
        assert first.status_code == 200
        busy = "worker busy, a native call is in flight"
        assert busy in first.text and "Deployment" in first.text
        assert value_of(first.text, "Listens on") == "127.0.0.1:47632 (loopback only)"
        assert "Full doctor report" not in first.text
        assert len(doc.calls) == 1

        second = get("/health")  # a call is still in flight: no second call starts
        assert busy in second.text and "Deployment" in second.text
        assert len(doc.calls) == 1
    finally:
        doc.gate.set()
    deadline = time.monotonic() + 5
    while health._lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not health._lock.locked()  # the abandoned thread released the lock
    third = get("/health")
    assert "worker busy" not in third.text and "Full doctor report" in third.text
    assert len(doc.calls) == 2


def test_health_an_exception_in_doctor_never_sticks_the_lock(doc, monkeypatch):
    def boom(request=False):
        raise RuntimeError("EventKit exploded <b>")

    monkeypatch.setattr(doctor, "diagnose", boom)
    r = get("/health")
    assert r.status_code == 200
    assert "doctor could not run" in r.text and "EventKit exploded &lt;b&gt;" in r.text
    assert not health._lock.locked()
    monkeypatch.setattr(doctor, "diagnose", doc.diagnose)
    assert "Full doctor report" in get("/health").text


# --- Health: what cannot work (D-14) ----------------------------------------------

FDA_DENIED = {"full_disk_access": ("fda", False, "denied")}
SETTINGS = "x-apple.systempreferences:com.apple.preference.security?"
EVERYONE = sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})


def banner(text):
    m = re.search(
        r'<div class="banner bad"><span>●</span><div><b>(.*?)</b> (.*?)</div></div>',
        text,
        re.S,
    )
    return (html.unescape(m.group(1)), html.unescape(m.group(2))) if m else None


def row_of(text, title):
    chunks = text.split('<div class="row')
    return next(c for c in chunks if f'<div class="title">{title}</div>' in c)


def only_active(monkeypatch, names):
    monkeypatch.setattr(
        registry, "adapter_status", lambda: {"registered": names, "configured": names}
    )


def needing(service):
    return sorted(
        a
        for a, needs in grants.ADAPTER_GRANTS.items()
        if any(s == service for s, _ in needs)
    )


def test_banner_names_every_active_adapter_macos_refused(doc):
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    names = needing("kTCCServiceSystemPolicyAllFiles")
    assert len(names) == 4  # mail, messages, photos, reminders
    head, rest = banner(get("/health").text)
    assert head == "4 active adapters cannot work:"
    listed = ", ".join(f"{n.capitalize()} (denied)" for n in names)
    assert rest == f"{listed}. Grant access, or turn the adapter off."


def test_banner_counts_only_the_active_set(doc, monkeypatch):
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    only_active(monkeypatch, ["photos"])
    head, rest = banner(get("/health").text)
    assert head == "1 active adapter cannot work:"
    assert rest == "Photos (denied). Grant access, or turn the adapter off."


def test_no_banner_when_every_grant_is_granted(doc):
    doc.report = make_report(make_ids(skip=()))
    text = get("/health").text
    assert "banner bad" not in text and "Automation →" not in text


def test_an_automation_denial_is_a_row_and_a_banner_entry(doc):
    doc.report = make_report(make_ids(skip=(), denied=("notes",)))
    text = get("/health").text
    assert banner(text)[0] == "1 active adapter cannot work:"
    assert banner(text)[1].startswith("Notes (denied).")
    row = row_of(text, "Automation → Notes")
    assert "dot bad" in row and ">Denied<" in row
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row


def test_automation_row_not_asked_has_an_accent_dot_and_a_settings_link(doc):
    row = row_of(get("/health").text, "Automation → Music")  # no TCC row for Music
    assert "dot warn" in row and "not asked" in row.lower()
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row


def test_an_off_adapter_raises_no_banner_and_says_it_does_not_matter(doc, monkeypatch):
    only_active(monkeypatch, [a for a in EVERYONE if a != "music"])
    text = get("/health").text
    row = row_of(text, "Automation → Music")
    assert not re.search(r"dot (ok|warn|bad)", row)
    assert "· adapter is off, so this does not matter" in row
    assert "Open Settings" not in row
    assert "banner bad" not in text


def test_an_unreadable_tcc_database_says_so_and_never_claims_not_asked(
    doc, monkeypatch
):
    doc.report = make_report(
        None, calendar=("eventkit", False, "denied")
    )  # TCC unreadable: the EventKit surface is the source
    doc.reasons = {"user": "absent", "system": "absent"}
    text = get("/health").text
    assert banner(text) == (
        "1 active adapter cannot work:",
        "Calendar (denied). Grant access, or turn the adapter off.",
    )
    assert "could not be read" in text and "user db: absent" in text
    assert "not asked" not in text.lower() and "Automation → " not in text
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row_of(
        text, "Automation"
    )


def test_a_partial_tcc_read_never_claims_not_asked(doc):
    # this Mac: the user database is absent, the system one answered with the FDA row
    ids = {"kTCCServiceSystemPolicyAllFiles": [{"client": BUNDLE, "granted": True}]}
    doc.report = make_report(ids)
    doc.reasons = {"user": "absent", "system": None}
    text = get("/health").text
    assert "not asked" not in text.lower() and "banner bad" not in text
    assert "could not be read" in text and "Automation → " not in text


def test_a_grant_with_a_status_is_not_a_denial(doc):
    ids = make_ids(skip=())
    ids["kTCCServiceCalendar"][0].update(granted=False, status="limited")
    doc.report = make_report(ids)
    assert "banner bad" not in get("/health").text


def nav_health(text):
    m = re.search(r'<a class="nav-item[^"]*" href="/health"[^>]*>(.*?)</a>', text, re.S)
    return m.group(1)


def test_the_sidebar_dot_follows_the_last_health_report(doc, monkeypatch):
    assert "dot" not in nav_health(get("/usage").text)  # before any report
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    get("/health")
    assert '<span class="dot bad"></span>' in nav_health(get("/usage").text)
    doc.report = make_report(make_ids(skip=()))
    get("/health")
    assert '<span class="dot ok"></span>' in nav_health(get("/usage").text)
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": EVERYONE, "configured": EVERYONE[:-1]},
    )
    get("/health")
    assert '<span class="dot warn"></span>' in nav_health(get("/usage").text)
