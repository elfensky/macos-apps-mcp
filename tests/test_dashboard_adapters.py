"""The Adapters page (PLAT-01, PLAT-02): toggles, pending chips, the restart bar.

Same harness as ``test_dashboard_guard.py``: ``httpx.ASGITransport`` inside
``asyncio.run``, no socket. Every test points the adapters_off file and the XDG state
dir at ``tmp_path``, so no test touches the developer's real files.
"""

import json
import os
import re
import stat
from urllib.parse import urlencode

import pytest

from macos_apps_mcp import audit, deploy, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from tests import _dashboard
from tests._dashboard import ORIGIN, TOKEN

FORM = {**_dashboard.FORM, "origin": ORIGIN}
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
    return _dashboard.request(method, path, app=app, headers=headers, content=content)


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
    return _dashboard.build(restart=fake)


def test_restart_answers_the_restarting_page_then_runs_the_hook_once(state):
    fake = _OneShot()
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
    n = sum(registry.TOOLS[t].registered for t in registry.by_adapter("photos"))
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


# --- post-merge review of #412 --------------------------------------------------------


def test_sidebar_badge_divides_by_every_known_adapter(state, monkeypatch):
    # Photos off at start and in the file: 9 registered of 10, never "9/9".
    running = [a for a in ADAPTERS if a != "photos"]
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": running, "configured": running},
    )
    assert '<span class="count">9/10</span>' in _get().text


def test_a_file_that_turns_unreadable_mid_request_is_not_overwritten(
    state, monkeypatch
):
    from macos_apps_mcp.dashboard import adapters

    real, seen = adapters._lock_reason, []

    def early_check_passes():  # the file becomes unreadable after the early check
        seen.append(1)
        return None if len(seen) == 1 else real()

    monkeypatch.setattr(adapters, "_lock_reason", early_check_passes)
    _file().parent.mkdir(parents=True)
    _file().write_text("music")
    _file().chmod(0)
    try:
        r = _toggle("photos", "0")
        assert r.status_code == 409 and "permissions" in r.text
        assert _records() == []
    finally:
        _file().chmod(0o600)
    assert _file().read_text() == "music"


class _OneShot(_Restart):
    """The daemon's hook: True the first time, False while a restart is under way."""

    def __call__(self):
        super().__call__()
        return self.calls == 1


def test_a_second_restart_while_one_is_under_way_logs_nothing(state):
    fake = _OneShot()
    app = _restart_app(fake)
    _post("/restart", app=app)
    _post("/restart", app=app)
    assert fake.calls == 2
    assert [r["op"] for r in _records()] == ["restart"]


def test_a_failed_write_leaves_no_audit_record(state, monkeypatch):
    def boom(names):
        raise OSError("disk full")

    monkeypatch.setattr(deploy, "write_adapters_off", boom)
    with pytest.raises(OSError, match="disk full"):
        _toggle("photos", "0")
    assert _records() == []


@pytest.mark.parametrize("status", ["limited", "unknown"])
def test_a_non_binary_grant_is_no_denied_chip(status):
    grants = _grants()
    row = _ident(("kTCCServiceCalendar", False, {"status": status}))
    assert grants.grant_state(row, "calendar") is None


def test_the_row_counts_registered_tools_only(state, monkeypatch):
    import dataclasses

    for name in registry.by_adapter("photos"):
        rec = dataclasses.replace(registry.TOOLS[name], registered=False)
        monkeypatch.setitem(registry.TOOLS, name, rec)
    assert "Full Disk Access · 0 tools</div>" in _row_html(_get().text, "Photos")


# --- refusals in the frame; Restart locks with the switches (#428) --------------------

_BACK = '<a href="/adapters">Back to the switches</a>'
_BAD = "Unknown action, adapter or value. Nothing changed."


def _framed(r, status, needle):
    assert r.status_code == status
    assert r.headers["content-type"].startswith("text/html")
    assert 'class="b-shell' in r.text and 'class="banner warn"' in r.text
    assert _BACK in r.text
    assert r.text.count(needle) == 1


@pytest.mark.parametrize(
    "case", ["env", "file", "discard", "unknown", "empty", "bad_value"]
)
def test_a_refused_toggle_renders_in_the_frame_with_a_way_back(
    state, monkeypatch, case
):
    if case in ("env", "discard"):
        monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")
    if case == "file":
        _file().parent.mkdir(parents=True)
        _file().write_text("music")
        _file().chmod(0)
    try:
        if case in ("env", "file"):
            send, status = (lambda: _toggle("music", "0")), 409
        elif case == "discard":
            send, status = (lambda: _post(action="discard")), 409
        elif case == "unknown":
            send, status = (lambda: _toggle("nosuch", "0")), 400
        elif case == "bad_value":
            send, status = (lambda: _toggle("photos", "2")), 400
        else:
            send, status = (lambda: _post()), 400  # only the token
        needle = {
            "file": "permissions",
            "env": "MACOS_APPS_ADAPTERS_OFF is set",
            "discard": "MACOS_APPS_ADAPTERS_OFF is set",
        }.get(case, _BAD)
        for _ in range(2):  # a repeated refusal answers the same and writes nothing
            _framed(send(), status, needle)
    finally:
        if case == "file":
            _file().chmod(0o600)
    if case == "file":
        assert _file().read_text() == "music"  # the unreadable file's intent survived
    elif case in ("unknown", "empty", "bad_value"):
        assert not _file().exists()
    assert _records() == []


def test_a_bad_action_never_echoes_the_posted_value(state):
    r = _post(action="toggle", adapter="<script>x</script>", on="1")
    _framed(r, 400, _BAD)
    assert "<script>x" not in r.text


@pytest.mark.parametrize("lock", ["env", "file"])
def test_restart_is_locked_with_the_switches(state, monkeypatch, lock):
    if lock == "env":
        monkeypatch.setenv("MACOS_APPS_ADAPTERS_OFF", "photos")
    else:
        _file().parent.mkdir(parents=True)
        _file().write_text("music")
        _file().chmod(0)
    fake = _OneShot()
    app = _restart_app(fake)
    try:
        # A pending change makes the bar show when nothing locks (the lock hides it).
        monkeypatch.setattr(
            registry,
            "adapter_status",
            lambda: {"registered": ADAPTERS, "configured": ADAPTERS[1:]},
        )
        page = _get(app=app).text
        assert 'action="/restart"' not in page and 'class="restart-bar"' not in page
        r = _post("/restart", app=app)
        _framed(r, 409, "permissions" if lock == "file" else "is set for this daemon")
    finally:
        if lock == "file":
            _file().chmod(0o600)
    assert fake.calls == 0 and _records() == []


def test_guard_refusals_stay_plain_text(state):
    r = _call(
        "POST", "/adapters", content=urlencode({"action": "discard"}), headers=FORM
    )
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/plain")
    assert "b-shell" not in r.text
    r = _dashboard.request("GET", "/adapters", cookie=False)
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/plain")
    assert "b-shell" not in r.text
