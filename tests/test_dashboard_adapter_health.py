"""#497: completed Health reports drive chips without native work on Adapters.

All reports are synthetic. ASGI requests use no listener or running daemon.
"""

import html
import re
import subprocess
import sys
import threading
from datetime import datetime

import pytest

from macos_apps_mcp import deploy, doctor, runtime
from macos_apps_mcp import server as _server  # noqa: F401 — populate the registry
from macos_apps_mcp.dashboard import grants, health
from tests._dashboard import get

STAMP = "2026-11-04 12:34:56"
AUTOMATION = [
    name
    for name, needs in grants.ADAPTER_GRANTS.items()
    if any(svc == grants.EVENTS for svc, _ in needs)
]


def _forbidden(*args, **kwargs):
    raise AssertionError("Adapters must not schedule a native check")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(health, "_last", None)
    monkeypatch.setattr(health, "_dot", None)
    monkeypatch.setattr(health, "_lock", threading.Lock())
    monkeypatch.setattr(doctor, "diagnose", _forbidden)
    monkeypatch.setattr(doctor, "run_native", _forbidden)
    monkeypatch.setattr(runtime, "run_native", _forbidden)
    monkeypatch.setattr(runtime, "run_osascript", _forbidden)
    monkeypatch.setattr(deploy, "grant_report", _forbidden)


def _ids(adapter="notes", automation=None, fda=True):
    ids = {}
    if fda is not None:
        ids[grants.FDA] = [{"client": deploy.BUNDLE_ID, "granted": fda}]
    if automation is not None:
        target = next(
            t for s, t in grants.ADAPTER_GRANTS[adapter] if s == grants.EVENTS
        )
        ids[grants.EVENTS] = [
            {"client": deploy.BUNDLE_ID, "target": target, "granted": automation}
        ]
    return ids


def _got(ids=None, *, complete=False, **live):
    return {
        "report": {
            "version": "test",
            "build": "test",
            "deployment": {"grant_identities": ids},
            "surfaces": [
                {"surface": name, "kind": "automation", "status": status}
                for name, status in live.items()
            ],
        },
        "reasons": {"user": None if complete else "absent", "system": None},
        "checked_at": STAMP,
    }


def _chip(text, adapter):
    (row,) = [
        row
        for row in text.split('<div class="row">')
        if f'aria-label="{adapter.capitalize()} adapter, ' in row
    ]
    chips = re.findall(r'<span class="chip(?: danger)?">(.*?)</span>', row)
    assert len(chips) <= 1
    return chips[0] if chips else None


@pytest.mark.parametrize(
    ("complete", "automation", "expected"),
    [
        (False, None, None),
        (True, None, "not asked"),
        (False, False, "denied"),
        (False, True, None),
    ],
)
def test_before_first_health_report_retains_tcc_chips(
    monkeypatch, complete, automation, expected
):
    got = _got(_ids(automation=automation), complete=complete)
    monkeypatch.setattr(
        deploy,
        "grant_report",
        lambda: {
            "identities": got["report"]["deployment"]["grant_identities"],
            "reasons": got["reasons"],
        },
    )
    response = get("/adapters")
    assert response.status_code == 200
    assert _chip(response.text, "notes") == expected
    assert response.text.count("Permission status uses the macOS grant database.") == 1
    assert (
        'Open <a href="/health">Health</a> to check Automation access.' in response.text
    )
    assert "last Health check" not in response.text and health._last is None


@pytest.mark.parametrize("adapter", AUTOMATION)
@pytest.mark.parametrize(
    ("live", "tcc", "complete", "expected"),
    [
        ("granted", False, False, "granted"),
        ("granted", None, False, "granted"),
        ("denied", True, False, "denied"),
        ("not_asked", True, False, "not asked"),
        ("probe_error", False, False, "denied"),
        ("probe_error", True, False, "granted"),
        ("probe_error", None, False, None),
        ("probe_error", None, True, "not asked"),
        ("not_running", None, False, None),
        ("not_running", False, False, "denied"),
        ("not_running", True, False, "granted"),
        ("adapter_off", False, False, "denied"),
        (None, False, False, "denied"),
    ],
)
def test_each_app_uses_health_live_tcc_precedence(
    monkeypatch, adapter, live, tcc, complete, expected
):
    assert AUTOMATION  # discovery must cover the Automation population
    got = _got(
        _ids(adapter, tcc),
        complete=complete,
        **({adapter: live} if live is not None else {}),
    )
    monkeypatch.setattr(health, "_last", got)
    assert health.last_permissions([adapter]) == ({adapter: expected}, STAMP)
    response = get("/adapters")
    assert response.status_code == 200
    assert _chip(response.text, adapter) == (
        expected if expected in ("denied", "not asked") else None
    )
    assert f"last Health check: {STAMP} (local time)" in response.text
    assert 'http-equiv="refresh"' not in response.text


@pytest.mark.parametrize("adapter", ["mail", "messages"])
@pytest.mark.parametrize(
    ("live", "fda", "complete", "expected"),
    [
        ("granted", False, False, "denied"),
        ("granted", None, True, "not asked"),
        ("granted", None, False, None),
        ("denied", None, False, "denied"),
        ("not_asked", False, False, "denied"),
        ("not_asked", None, False, "not asked"),
        ("probe_error", False, False, "denied"),
    ],
)
def test_automation_cannot_hide_other_required_grants(
    monkeypatch, adapter, live, fda, complete, expected
):
    got = _got(_ids(adapter, fda=fda), complete=complete, **{adapter: live})
    monkeypatch.setattr(health, "_last", got)
    assert health.last_permissions([adapter]) == ({adapter: expected}, STAMP)
    text = get("/adapters").text
    assert _chip(text, adapter) == expected
    assert _chip(text, "photos") == (
        "denied" if fda is False else "not asked" if fda is None and complete else None
    )
    assert _chip(text, "shortcuts") is None


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([], None),
        (["granted"], "granted"),
        (["granted", "granted"], "granted"),
        (["granted", None], None),
        (["granted", "unknown"], None),
        (["granted", "not running"], None),
        ([None, "not asked"], "not asked"),
        ([None, "not asked", "denied"], "denied"),
    ],
)
def test_combined_permission_precedence(states, expected):
    assert grants.combined_state(iter(states)) == expected
    assert grants.combined_state(reversed(states)) == expected


def test_cached_timestamp_is_escaped(monkeypatch):
    got = _got()
    got["checked_at"] = '<script>"time" & wrong</script>'
    monkeypatch.setattr(health, "_last", got)
    text = get("/adapters").text
    assert html.escape(got["checked_at"], quote=True) in text
    assert got["checked_at"] not in text


def test_chips_and_timestamp_use_one_report_even_if_health_finishes(monkeypatch):
    old = _got(notes="denied")
    new = _got(notes="granted")
    new["checked_at"] = "2026-11-04 14:00:00"
    monkeypatch.setattr(health, "_last", old)
    original = health._automation_state

    def replace_report(got, adapter):
        health._last = new
        return original(got, adapter)

    monkeypatch.setattr(health, "_automation_state", replace_report)
    first = get("/adapters").text
    assert _chip(first, "notes") == "denied"
    assert STAMP in first and new["checked_at"] not in first
    second = get("/adapters").text
    assert _chip(second, "notes") is None and new["checked_at"] in second


class Clock:
    value = datetime(2026, 11, 4, 12, 34, 56, 789012)

    def now(self):
        return self.value


def _fake_health(monkeypatch, got):
    monkeypatch.setattr(doctor, "diagnose", lambda request=False: got["report"])
    monkeypatch.setattr(deploy, "grant_report", lambda: {"reasons": got["reasons"]})


def test_health_publishes_timestamp_only_after_both_reads_complete(monkeypatch):
    old = _got(notes="denied")
    new = _got(notes="granted")
    clock = Clock()
    monkeypatch.setattr(health, "datetime", clock)
    monkeypatch.setattr(health, "_last", old)

    def diagnose(request):
        assert request is False and health._last is old
        clock.value = datetime(2026, 11, 4, 12, 40)
        return new["report"]

    def grant_report():
        assert health._last is old
        clock.value = datetime(2026, 11, 4, 12, 45, 30, 123456)
        return {"reasons": new["reasons"]}

    monkeypatch.setattr(doctor, "diagnose", diagnose)
    monkeypatch.setattr(deploy, "grant_report", grant_report)
    assert get("/health").status_code == 200
    assert health._last == {**new, "checked_at": "2026-11-04 12:45:30"}
    clock.value = datetime(2026, 11, 5, 18)
    text = get("/adapters").text
    assert "2026-11-04 12:45:30 (local time)" in text
    assert "2026-11-05" not in text and _chip(text, "notes") is None


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize("failed_read", ["doctor", "tcc"])
def test_failed_health_preserves_last_completed_report(
    monkeypatch, previous, failed_read
):
    old = _got(notes="denied") if previous else None
    monkeypatch.setattr(health, "_last", old)
    _fake_health(monkeypatch, _got(notes="granted"))

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic check failure")

    monkeypatch.setattr(
        doctor if failed_read == "doctor" else deploy,
        "diagnose" if failed_read == "doctor" else "grant_report",
        fail,
    )
    response = get("/health")
    assert response.status_code == 200 and "doctor could not run" in response.text
    assert health._last is old and not health._lock.locked()
    monkeypatch.setattr(
        deploy,
        "grant_report",
        lambda: {"identities": {}, "reasons": {"user": "absent", "system": None}},
    )
    text = get("/adapters").text
    assert _chip(text, "notes") == ("denied" if previous else None)
    assert (STAMP in text) is previous
    # Failure releases the scheduling lock; a later completed check can replace it.
    _fake_health(monkeypatch, _got(notes="granted"))
    assert get("/health").status_code == 200
    assert health._last is not old and _chip(get("/adapters").text, "notes") is None


@pytest.mark.parametrize("previous", [False, True])
def test_in_flight_health_keeps_old_chips_and_publishes_after_request_timeout(
    monkeypatch, previous
):
    old = _got(notes="denied") if previous else None
    new = _got(notes="granted")
    monkeypatch.setattr(health, "_last", old)
    monkeypatch.setattr(health, "_WAIT", 0.1)
    clock = Clock()
    monkeypatch.setattr(health, "datetime", clock)
    entered, release, finished = (threading.Event() for _ in range(3))
    calls = []

    def diagnose(request):
        calls.append(request)
        entered.set()
        assert release.wait(5), "test did not release synthetic diagnosis"
        return new["report"]

    def run():
        try:
            return original_run()
        finally:
            finished.set()

    original_run = health._run
    monkeypatch.setattr(health, "_run", run)
    monkeypatch.setattr(doctor, "diagnose", diagnose)
    monkeypatch.setattr(
        deploy,
        "grant_report",
        lambda: {"identities": {}, "reasons": new["reasons"]},
    )
    try:
        assert "worker busy" in get("/health").text
        assert entered.wait(2) and health._last is old
        text = get("/adapters").text
        assert _chip(text, "notes") == ("denied" if previous else None)
        assert (STAMP in text) is previous
        assert "worker busy" in get("/health").text
        assert calls == [False] and health._run() is None
        assert health._last is old  # refused concurrent run publishes nothing
        finished.clear()  # the refused run finished; the first remains in flight
        clock.value = datetime(2026, 11, 4, 15, 0, 1)
    finally:
        release.set()
        assert finished.wait(5), "synthetic Health worker did not finish"
    assert not health._lock.locked()
    text = get("/adapters").text
    assert _chip(text, "notes") is None
    assert "2026-11-04 15:00:01 (local time)" in text and calls == [False]


@pytest.mark.parametrize("first", ["adapters", "health", "grants"])
def test_fresh_dashboard_imports_have_no_native_work_or_import_cycle(first):
    code = """
import importlib
import sys
from macos_apps_mcp import runtime
def forbidden(*args, **kwargs):
    raise AssertionError('native work during dashboard import')
runtime.run_native = runtime.run_osascript = forbidden
importlib.import_module('macos_apps_mcp.dashboard.' + sys.argv[1])
from macos_apps_mcp.dashboard import adapters, health, build_app
assert callable(adapters.page) and callable(health.page) and callable(build_app)
assert health._last is None
"""
    result = subprocess.run(
        [sys.executable, "-c", code, first], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
