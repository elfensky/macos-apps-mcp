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
