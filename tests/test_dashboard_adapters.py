"""The Adapters page (PLAT-01, PLAT-02): toggles, pending chips, the restart bar.

Same harness as ``test_dashboard_guard.py``: ``httpx.ASGITransport`` inside
``asyncio.run``, no socket. Every test points the adapters_off file and the XDG state
dir at ``tmp_path``, so no test touches the developer's real files.
"""

import asyncio
import json
import os
import re
import stat
from urllib.parse import urlencode

import httpx
import pytest

from macos_apps_mcp import audit, dashboard, deploy, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS

PORT = 47632
TOKEN = "tok"
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
FORM = {"content-type": "application/x-www-form-urlencoded", "origin": ORIGIN}
ADAPTERS = sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})


@pytest.fixture
def state(tmp_path, monkeypatch):
    """The daemon role, an empty deny-list file path and a private state dir."""
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.delenv("MACOS_APPS_ADAPTERS_OFF", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(
        deploy, "_ADAPTERS_OFF_FILE", tmp_path / "state" / "adapters_off"
    )
    return tmp_path


def _file():
    return deploy._ADAPTERS_OFF_FILE


def _records():
    path = audit._audit_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _call(method, path, *, content=None, headers=None, app=None):
    async def go():
        transport = httpx.ASGITransport(
            app=app or dashboard.build_app(port=PORT, token=TOKEN)
        )
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as c:
            return await c.request(method, path, headers=headers, content=content)

    return asyncio.run(go())


def _get(path="/adapters", **kw):
    return _call("GET", path, **kw)


def _post(path="/adapters", *, app=None, **form):
    body = urlencode({"token": TOKEN, **form})
    return _call("POST", path, content=body, headers=FORM, app=app)


def _toggle(adapter, on):
    return _post(action="toggle", adapter=adapter, on=on)


def test_adapters_page_lists_every_adapter_alphabetically_as_token_forms(state):
    r = _get()
    assert r.status_code == 200
    names = re.findall(
        r'<button type="submit" class="switch"[^>]*aria-label="(\w+)"', r.text
    )
    assert names == [a.capitalize() for a in ADAPTERS] and len(names) == 10
    assert (
        r.text.count('<form method="post" action="/adapters" class="switch-form">')
        == 10
    )
    assert r.text.count('<input type="hidden" name="token" value="tok">') >= 10
    assert 'class="restart-bar"' not in r.text
    assert re.search(r'<a class="nav-item[^"]*" href="/adapters"', r.text)
    assert (
        "Turn an app off and its tools disappear after the daemon restarts." in r.text
    )


def test_toggle_off_writes_the_file_and_one_dashboard_audit_record(state, monkeypatch):
    def no_usage(*a, **kw):
        raise AssertionError("a dashboard write must not count as a tool call")

    monkeypatch.setattr(audit, "usage_log", no_usage)
    r = _toggle("photos", "0")
    assert r.status_code == 303 and r.headers["location"] == "/adapters"
    assert _file().read_text() == "photos"
    (rec,) = _records()
    assert rec.pop("ts")
    assert rec == {
        "tool": "dashboard",
        "op": "toggle",
        "args": {"adapter": "photos", "on": False},
        "dry_run": False,
        "caller": "dashboard",
        "target_id": "photos",
        "before": None,
        "after": None,
    }


def test_toggle_shows_the_pending_chip_and_the_restart_bar(state):
    _toggle("photos", "0")
    page = _get().text
    assert "off after restart" in page
    assert "<b>1 change waits for a restart.</b>" in page
    _toggle("music", "0")
    page = _get().text
    assert "<b>2 changes wait for a restart.</b>" in page
    assert _file().read_text() == "music,photos"
    _toggle("music", "1")  # back on: nothing waits for it any more
    assert _file().read_text() == "photos"
    assert "<b>1 change waits for a restart.</b>" in _get().text


def test_toggle_rewrites_the_file_with_known_names_only(state):
    _file().parent.mkdir(parents=True)
    _file().write_text("photos,nosuch")
    _toggle("music", "0")
    assert _file().read_text() == "music,photos"


@pytest.mark.parametrize(
    "form",
    [
        {"adapter": "nosuch", "on": "0"},  # unknown adapter name (D-01)
        {"adapter": "photos", "on": "2"},
        {"adapter": "photos"},
        {"on": "0"},
    ],
)
def test_toggle_unknown_adapter_or_bad_value_is_400_and_changes_nothing(state, form):
    assert _post(action="toggle", **form).status_code == 400
    assert not _file().exists() and _records() == []


def test_atomic_write_failure_keeps_the_old_file_and_leaves_no_temp(state, monkeypatch):
    deploy.write_adapters_off(["music"])
    assert _file().read_text() == "music"

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        deploy.write_adapters_off(["photos"])
    assert _file().read_text() == "music"
    assert [p.name for p in _file().parent.iterdir()] == ["adapters_off"]


def test_write_adapters_off_makes_a_0700_directory_and_sorts_the_names(state):
    deploy.write_adapters_off(["photos", "music", "photos"])
    assert _file().read_text() == "music,photos"
    assert stat.S_IMODE(_file().parent.stat().st_mode) == 0o700


def test_get_is_side_effect_free(state):
    _toggle("photos", "0")
    before = (_file().read_bytes(), audit._audit_path().read_bytes())
    _get()
    _get()
    assert (_file().read_bytes(), audit._audit_path().read_bytes()) == before


# --- restart, Discard, the env override and an unreadable file (Task 2) ---------------


class _Restart:
    """Records calls of the ``restart`` hook ``build_app`` is given."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def _restart_app(fake):
    return dashboard.build_app(port=PORT, token=TOKEN, restart=fake)


def test_restart_answers_the_restarting_page_then_runs_the_hook_once(state):
    fake = _Restart()
    r = _post("/restart", app=_restart_app(fake))
    assert r.status_code == 200
    assert "Restarting the daemon…" in r.text
    assert '<meta http-equiv="refresh" content="12;url=/adapters">' in r.text
    assert '<a href="/adapters">Reload</a>' in r.text
    assert 'class="spin"' in r.text and "restarting" in r.text
    assert fake.calls == 1
    (rec,) = _records()
    assert rec.pop("ts")
    assert rec["tool"] == "dashboard" and rec["op"] == "restart"
    assert rec["args"] == {} and rec["caller"] == "dashboard"
    assert rec["dry_run"] is False and rec["target_id"] is None


def test_restart_needs_the_token_and_refuses_get(state):
    fake = _Restart()
    app = _restart_app(fake)
    no_token = _call("POST", "/restart", content="", headers=FORM, app=app)
    assert no_token.status_code == 403 and fake.calls == 0 and _records() == []
    assert _call("GET", "/restart", app=app).status_code == 405
    assert fake.calls == 0


def test_restart_without_a_hook_is_503_and_logs_nothing(state):
    r = _post("/restart")  # a test app, never the daemon
    assert r.status_code == 503 and "only in the daemon" in r.text
    assert _records() == []


def test_discard_writes_the_running_set_back_and_logs_it(state):
    _toggle("music", "0")
    _toggle("photos", "0")
    assert "<b>2 changes wait for a restart.</b>" in _get().text
    r = _post(action="discard")
    assert r.status_code == 303 and _file().read_text() == ""
    rec = _records()[-1]
    assert rec["op"] == "discard" and rec["caller"] == "dashboard"
    assert rec["args"] == {"adapters_off": []} and rec["target_id"] is None
    assert 'class="restart-bar"' not in _get().text


def test_discard_keeps_an_adapter_that_did_not_register_off(state, monkeypatch):
    running = [a for a in ADAPTERS if a != "photos"]
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": running, "configured": ADAPTERS},
    )
    assert _post(action="discard").status_code == 303
    assert _file().read_text() == "photos"
    assert _records()[-1]["args"] == {"adapters_off": ["photos"]}


def test_env_override_disables_the_switches_and_refuses_writes(state, monkeypatch):
    monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")
    page = _get().text
    assert page.count("disabled") >= 10
    assert (
        "MACOS_APPS_ADAPTERS_OFF is set for this daemon and wins over the file. "
        "Unset it to use these switches." in page
    )
    assert _toggle("music", "0").status_code == 409
    assert _post(action="discard").status_code == 409
    assert not _file().exists() and _records() == []


def test_unreadable_file_reads_every_switch_off_and_refuses_writes(state):
    _file().parent.mkdir(parents=True)
    _file().write_text("music")
    _file().chmod(0)
    try:
        page = _get().text
        assert page.count('aria-pressed="false"') == 10
        assert 'aria-pressed="true"' not in page
        assert "cannot be read" in page
        assert ">*<" not in page and 'aria-label="*"' not in page
        for r in (_toggle("photos", "0"), _post(action="discard")):
            assert r.status_code == 409 and "permissions" in r.text
        assert _records() == []
    finally:
        _file().chmod(0o600)
    assert _file().read_text() == "music"  # the unreadable file's intent survived
