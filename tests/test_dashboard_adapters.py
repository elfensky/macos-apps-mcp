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


# --- the rows say why: grants, counts, the locked Outbound row (Task 3) ---------------

CLIENT = "ren.lav.macos-apps-mcp"
_KIND = {
    "kTCCServiceCalendar": "EventKit",
    "kTCCServiceReminders": "EventKit",
    "kTCCServiceAppleEvents": "Automation",
    "kTCCServiceSystemPolicyAllFiles": "Full Disk Access",
}


def _grants():
    from macos_apps_mcp.dashboard import grants

    return grants


def test_grants_cover_every_adapter_with_the_permissions_its_records_name():
    grants = _grants()
    assert set(grants.ADAPTER_GRANTS) == set(ADAPTERS)
    for adapter in ADAPTERS:
        named = {
            p
            for r in registry.TOOLS.values()
            if r.adapter == adapter
            for p in r.permission
        } - {"Shortcuts CLI"}  # the CLI needs no TCC grant
        listed = {_KIND[svc] for svc, _target in grants.ADAPTER_GRANTS[adapter]}
        assert listed == named, adapter
        for svc, target in grants.ADAPTER_GRANTS[adapter]:
            assert (target is not None) == (svc == "kTCCServiceAppleEvents")


def _ident(*rows):
    out = {}
    for svc, granted, extra in rows:
        out.setdefault(svc, []).append({"client": CLIENT, "granted": granted, **extra})
    return out


def test_grant_state_reads_granted_denied_and_not_asked():
    grants = _grants()
    cal = "kTCCServiceCalendar"
    fda = "kTCCServiceSystemPolicyAllFiles"
    events = "kTCCServiceAppleEvents"
    assert grants.grant_state(_ident((cal, True, {})), "calendar") == "granted"
    assert grants.grant_state(_ident((fda, False, {})), "photos") == "denied"
    mail_fda = _ident((fda, True, {}))
    assert grants.grant_state(mail_fda, "mail") == "not asked"  # no AppleEvents row
    other = _ident((fda, True, {}), (events, True, {"target": "com.apple.Notes"}))
    assert grants.grant_state(other, "mail") == "not asked"  # another app's target
    both = _ident((fda, True, {}), (events, True, {"target": "com.apple.mail"}))
    assert grants.grant_state(both, "mail") == "granted"


def test_grant_state_is_unknown_when_it_cannot_tell():
    grants = _grants()
    cal = "kTCCServiceCalendar"
    assert grants.grant_state(None, "calendar") is None
    assert grants.grant_state(_ident((cal, True, {})), "shortcuts") is None
    other = {cal: [{"client": "com.example.other", "granted": False}]}
    assert grants.grant_state(other, "calendar") == "not asked"  # not our client
    # A TCC database that could not be read cannot say "not asked" (a wrong claim).
    assert grants.grant_state({}, "calendar", complete=False) is None
    assert grants.grant_state(_ident((cal, False, {})), "calendar", complete=False) == (
        "denied"
    )


def _row_html(page, label):
    (row,) = [
        r for r in page.split('<div class="row">') if f'aria-label="{label}"' in r
    ]
    return row


def test_grant_chips_and_the_row_sub_with_tool_and_call_counts(state, monkeypatch):
    report = {
        "identities": _ident(
            ("kTCCServiceCalendar", False, {}),
            ("kTCCServiceSystemPolicyAllFiles", True, {}),
        ),
        "reasons": {"user": None, "system": None},
    }
    monkeypatch.setattr(deploy, "grant_report", lambda *a, **kw: report)
    tool = sorted(registry.by_adapter("photos"))[0]
    usage = audit._usage_path()
    usage.write_text(
        "".join(json.dumps({"ts": "t", "tool": tool}) + "\n" for _ in "abc")
    )
    page = _get().text
    assert '<span class="chip danger">denied</span>' in _row_html(page, "Calendar")
    mail = _row_html(page, "Mail")
    assert '<span class="chip">not asked</span>' in mail
    assert "Automation · Full Disk Access · " in mail
    n = len(registry.by_adapter("photos"))
    assert f'<div class="sub">Full Disk Access · {n} tools · 3 calls</div>' in page
    photos = _row_html(page, "Photos")  # granted: no grant chip before the switch
    assert 'class="chip' not in photos.split("<form")[0]


def test_outbound_row_is_locked_text_with_the_command_and_no_form(state):
    sending = registry.outbound_status()["registered"]
    page = _get().text
    title = f"Outbound: {', '.join(sending) or 'off'}"
    assert f'<div class="title">{title}</div>' in page
    section = page.split("Sending off this Mac")[1].split('<p class="muted note">')[0]
    assert 'class="row locked"' in section
    assert (
        "Never changed from this page — any website could send a request to "
        "127.0.0.1. Change it in Terminal:" in section
    )
    command = "macos-apps-mcp allow-send " + ("off" if sending else "mail")
    assert f"<code>{command}</code>" in section
    assert f'data-copy="{command}"' in section
    assert "<form" not in section and "<input" not in section


def test_footer_note_names_the_file_and_the_dashboard_caller(state):
    assert (
        '<p class="muted note">Toggles write ~/.local/state/macos-apps-mcp/'
        "adapters_off. Each change is logged in audit.jsonl with caller "
        "<b>dashboard</b>.</p>"
    ) in _get().text


def test_sidebar_badge_counts_active_adapters_then_pending_changes(state):
    def badge():
        (nav,) = re.findall(
            r'<a class="nav-item[^"]*" href="/adapters".*?</a>', _get().text
        )
        return nav

    assert '<span class="count">10/10</span>' in badge()
    _toggle("photos", "0")
    _toggle("music", "0")
    assert (
        '<span class="count"><span class="chip pending">2 pending</span></span>'
        in badge()
    )
