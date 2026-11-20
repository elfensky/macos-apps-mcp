import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

import pytest

from macos_apps_mcp import daemon, deploy, doctor
from macos_apps_mcp.errors import NativeError

_REAL_IDENTITY = deploy._daemon_identity  # the `opened` fixture scripts the read


def _tcc_db(path, rows):
    """A five-column ``access`` table (#318) holding the given 5-tuples."""
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE access (service TEXT, client TEXT, auth_value INT, "
        "auth_reason INT, indirect_object_identifier TEXT)"
    )
    c.executemany("INSERT INTO access VALUES (?,?,?,?,?)", rows)
    c.commit()
    c.close()


def _fake_tcc(path):
    _tcc_db(
        path,
        [
            ("kTCCServiceCalendar", "com.apple.Terminal", 2, 2, "UNUSED"),
            ("kTCCServiceCalendar", "ren.lav.macos-apps-mcp", 2, 2, "UNUSED"),
            (
                "kTCCServiceSystemPolicyAllFiles",
                "ren.lav.macos-apps-mcp",
                0,
                3,
                "UNUSED",
            ),
        ],
    )


def test_session_points_tcc_at_absent_paths(_isolated_state):
    """WR-01: no unit test may read the developer's real TCC databases."""
    real = (
        Path.home() / "Library/Application Support/com.apple.TCC/TCC.db",
        Path("/Library/Application Support/com.apple.TCC/TCC.db"),
    )
    for p in (deploy._TCC_DB, deploy._TCC_SYSTEM_DB):
        assert not p.exists()
        assert p.is_relative_to(_isolated_state)
        assert p not in real
    assert doctor._FDA_PATHS == (deploy._TCC_DB, deploy._TCC_SYSTEM_DB)


def test_grant_identities_maps_rows(tmp_path, monkeypatch):
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    # pin the system db away — on a dev Mac with FDA the REAL one is readable and
    # its rows would leak into the assertions (#123)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent-sys" / "TCC.db")
    out = deploy.grant_identities(
        ["kTCCServiceCalendar", "kTCCServiceSystemPolicyAllFiles"]
    )
    cal = out["kTCCServiceCalendar"]
    assert {"client": "ren.lav.macos-apps-mcp", "granted": True} in cal
    assert {"client": "com.apple.Terminal", "granted": True} in cal
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": False, "reason": "user-set"}
    ]


def test_grant_identities_merges_system_db_fda(tmp_path, monkeypatch):
    # #123: FDA rows live ONLY in the system TCC db — the merge must surface them
    # even when the user db has no AllFiles row at all.
    user_db = tmp_path / "user.db"
    _tcc_db(
        user_db, [("kTCCServiceCalendar", "ren.lav.macos-apps-mcp", 2, 2, "UNUSED")]
    )
    sys_db = tmp_path / "system.db"
    _tcc_db(
        sys_db,
        [("kTCCServiceSystemPolicyAllFiles", "ren.lav.macos-apps-mcp", 2, 2, "UNUSED")],
    )
    monkeypatch.setattr(deploy, "_TCC_DB", user_db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", sys_db)
    out = deploy.grant_identities()
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": True}
    ]
    assert out["kTCCServiceCalendar"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": True}
    ]


def test_grant_identities_partial_when_one_db_unreadable(tmp_path, monkeypatch):
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent" / "TCC.db")
    out = deploy.grant_identities(["kTCCServiceCalendar"])
    assert out is not None and "kTCCServiceCalendar" in out


def test_grant_identities_unreadable_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_TCC_DB", tmp_path / "absent" / "TCC.db")
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent2" / "TCC.db")
    assert deploy.grant_identities() is None


# --- C7: TCC reads get honest failure classification --------------------------------


def test_tcc_rows_absent_is_classified(tmp_path):
    # C7: a missing db and a chmod-000 db produce BYTE-IDENTICAL sqlite
    # OperationalErrors — the old `except sqlite3.Error: return None` swallowed both.
    rows, reason = deploy._tcc_rows(tmp_path / "absent" / "TCC.db", ["kTCCServiceX"])
    assert rows is None and reason == "absent"


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_tcc_rows_permission_denied_is_fda(tmp_path):
    # mirror of test_sqlite_plane's chmod-000 stand-in for a real FDA denial.
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    os.chmod(db, 0o000)
    try:
        rows, reason = deploy._tcc_rows(db, ["kTCCServiceCalendar"])
        assert rows is None and reason == "no-full-disk-access"
    finally:
        os.chmod(db, 0o644)


def test_tcc_rows_dropped_column_is_schema_drift(tmp_path):
    db = tmp_path / "TCC.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE access (service TEXT, client TEXT)")  # auth_value gone
    c.commit()
    c.close()
    rows, reason = deploy._tcc_rows(db, ["kTCCServiceCalendar"])
    assert rows is None and reason == "schema-drift"


def test_tcc_rows_hash_in_path_still_reads(tmp_path):
    # the old raw f"file:{db}?mode=ro" URI truncated at a `#` fragment → "no such
    # table" → swallowed None; runtime's opener percent-quotes the path.
    d = tmp_path / "weird#dir"
    d.mkdir()
    db = d / "TCC.db"
    _fake_tcc(db)
    rows, reason = deploy._tcc_rows(db, ["kTCCServiceCalendar"])
    assert reason is None and len(rows) == 2


def test_grant_identities_limited_carries_status(tmp_path, monkeypatch):
    # C7: limited(3) (partial access) used to masquerade as a plain denial — it still
    # reports granted=False (wire-stable) but now carries status="limited".
    db = tmp_path / "TCC.db"
    _tcc_db(db, [("kTCCServiceCalendar", "limited.app", 3, 2, "UNUSED")])
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent" / "TCC.db")
    out = deploy.grant_identities(["kTCCServiceCalendar"])
    assert out["kTCCServiceCalendar"] == [
        {"client": "limited.app", "granted": False, "status": "limited"}
    ]


def test_grant_report_carries_classified_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_TCC_DB", tmp_path / "absent" / "TCC.db")
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent2" / "TCC.db")
    report = deploy.grant_report()
    assert report["identities"] is None
    assert report["reasons"] == {"user": "absent", "system": "absent"}


def test_agent_status_maps_ints(monkeypatch):
    class FakeSvc:
        def status(self):
            return 1

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    assert deploy.agent_status() == "enabled"


def test_register_agent_failure_raises(monkeypatch):
    class FakeSvc:
        def registerAndReturnError_(self, _):
            return (False, "boom")

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    with pytest.raises(NativeError, match="boom"):
        deploy.register_agent()


def test_unregister_agent_failure_raises(monkeypatch):
    class FakeSvc:
        def unregisterAndReturnError_(self, _):
            return (False, "boom")

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    with pytest.raises(NativeError, match="boom"):
        deploy.unregister_agent()


def test_agent_service_outside_bundle_raises(monkeypatch):
    # off-bundle: main-bundle id is None (a bare venv). Inject it so the test doesn't
    # depend on what the host's Python reports.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: None)
    with pytest.raises(NativeError, match="build_app.sh"):
        deploy._agent_service()


def test_agent_service_foreign_bundle_raises(monkeypatch):
    # a NON-None but foreign bundle id (e.g. the runner's org.python.python) must still
    # raise — the `is None` check missed this and reddened CI. Reproduce it.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: "org.python.python")
    with pytest.raises(NativeError, match="build_app.sh"):
        deploy._agent_service()


def test_agent_service_our_bundle_proceeds(monkeypatch):
    # our exact bundle id passes the gate: _agent_service goes on to call SMAppService.
    # Stub the framework seam so the positive path is asserted without a real bundle.
    monkeypatch.setattr(deploy, "_main_bundle_id", lambda: deploy.BUNDLE_ID)
    import sys
    import types

    fake_sm = types.ModuleType("ServiceManagement")
    fake_sm.SMAppService = types.SimpleNamespace(
        agentServiceWithPlistName_=lambda name: ("svc", name)
    )
    monkeypatch.setitem(sys.modules, "ServiceManagement", fake_sm)
    assert deploy._agent_service() == ("svc", deploy._PLIST)


def test_install_agent_missing_app_fails_actionably(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        deploy.install_agent(["--app", str(tmp_path / "nope.app")])
    assert e.value.code == 2
    assert "build_app.sh" in capsys.readouterr().err


def _app_with_wrapper(root):
    app = root / "macos-apps-mcp.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    exe = app / "Contents/MacOS/macos-apps-mcp"
    exe.write_text("")
    exe.chmod(0o755)
    (app / deploy._CLI_WRAPPER).parent.mkdir(parents=True)
    (app / deploy._CLI_WRAPPER).write_text("")
    return app


def test_install_agent_orchestrates(tmp_path, monkeypatch, capsys, cli_link):
    app = _app_with_wrapper(tmp_path)
    calls = []
    monkeypatch.setattr(deploy, "_run_bundle_role", lambda a, role: calls.append(role))
    # the any-answer mode: no wanted identity, so no comparison and no restart
    monkeypatch.setattr(deploy, "_wait_for_daemon", lambda: calls.append("daemon"))
    monkeypatch.setattr(
        deploy, "_request_grants_via_daemon", lambda: calls.append("prompts")
    )
    deploy.install_agent(["--app", str(app)])
    assert calls == ["register", "daemon", "prompts"]
    out = capsys.readouterr().out
    assert "Privacy_AllFiles" in out  # FDA deep-link printed
    assert '"shim"' in out  # client config snippet
    assert '"-E"' in out  # isolation flags pinned in printed snippet
    assert deploy._CLI_LINK.resolve() == (app / deploy._CLI_WRAPPER).resolve()
    assert f"CLI: {deploy._CLI_LINK}" in out


# --- the CLI link -------------------------------------------------------------------


@pytest.fixture
def cli_link(monkeypatch):
    """The patched link path, cleaned after; uninstall's bundle role never runs."""
    monkeypatch.setattr(deploy, "_run_bundle_role", lambda a, role: None)
    yield deploy._CLI_LINK
    deploy._CLI_LINK.unlink(missing_ok=True)


def test_link_cli_is_idempotent_and_uninstall_removes_it(tmp_path, cli_link):
    app = _app_with_wrapper(tmp_path)
    assert deploy._link_cli(app).startswith("CLI: ")
    assert deploy._link_cli(app).startswith("CLI: ")  # an existing own link is fine
    assert cli_link.resolve() == (app / deploy._CLI_WRAPPER).resolve()
    deploy.uninstall_agent()  # any app link goes, here one into a dev build
    assert not os.path.lexists(cli_link)


def test_link_cli_moves_a_broken_app_link_and_resolves_a_relative_app(
    tmp_path, monkeypatch, cli_link
):
    old = _app_with_wrapper(tmp_path / "old")
    new = _app_with_wrapper(tmp_path / "new")
    deploy._link_cli(old)
    shutil.rmtree(old)  # the dev build it pointed at is gone
    monkeypatch.chdir(tmp_path)
    assert deploy._link_cli(Path("new/macos-apps-mcp.app")).startswith("CLI: ")
    assert os.path.isabs(os.readlink(cli_link))
    assert cli_link.resolve() == (new / deploy._CLI_WRAPPER).resolve()


def test_link_cli_leaves_a_foreign_file_and_a_wrapperless_build_alone(
    tmp_path, cli_link
):
    app = _app_with_wrapper(tmp_path)
    uv_tool = "/elsewhere/uv/tools/macos-apps-mcp/bin/macos-apps-mcp"
    cli_link.parent.mkdir(parents=True, exist_ok=True)
    cli_link.symlink_to(uv_tool)
    assert "not an app link" in deploy._link_cli(app)
    deploy.uninstall_agent()
    assert os.readlink(cli_link) == uv_tool
    cli_link.unlink()
    (app / deploy._CLI_WRAPPER).unlink()  # an app built before the wrapper existed
    assert "no CLI wrapper" in deploy._link_cli(app)
    assert not os.path.lexists(cli_link)  # never a dangling link


# --- `launch`: what opening the .app does -------------------------------------------


class _Notice:
    """The child that shows the alert of the wait. A `stuck` one ignores the signal."""

    stuck = False

    def __init__(self, message):
        self.message, self.ended, self.reaped, self.killed = message, 0, 0, 0

    def terminate(self):
        self.ended += 1

    def wait(self, timeout):
        if self.stuck:
            raise subprocess.TimeoutExpired("osascript", timeout)
        self.reaped += 1

    def kill(self):
        self.killed += 1


@pytest.fixture
def sockdir():
    # AF_UNIX sun_path is ~104 bytes on macOS, and pytest's tmp_path is longer.
    d = Path(tempfile.mkdtemp(prefix="mcpsock-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _Clock:
    """`deploy.time` for a wait: `sleep` moves `monotonic`, so no test waits."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        # A wait that lost its bound must fail here, not hang the suite. A test that
        # runs the REAL read also needs the bound of that read
        # (test_daemon_identity_has_a_total_bound_for_a_peer_that_drips): no clock
        # can end a read that blocks.
        assert self.now <= 600, "the wait has no bound"  # twice the real bound


@pytest.fixture
def opened(tmp_path, monkeypatch, cli_link):
    """`launch` from an app at the patched install path. Only the native boundary is
    faked (agent status, registration, the daemon's identity answers, the restart, the
    clock, the alert of the wait, the daemon's dialog pass, the alert and the browser);
    the CLI link, the setup marker and the dashboard link are real. `answers` scripts
    the identity reads, and its last item repeats; the default is the app's own
    identity."""
    app = _app_with_wrapper(tmp_path).resolve()
    monkeypatch.setattr(deploy, "_APP", app)
    monkeypatch.setattr(sys, "executable", str(app / "Contents/MacOS/macos-apps-mcp"))
    deploy._DASHBOARD_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    deploy._DASHBOARD_KEY_FILE.write_text("k" * 43)
    state = {"status": "enabled", "dialogs": 0, "fail": None}
    mine = (doctor.version(), doctor.build_stamp())
    seen = {"urls": [], "alerts": [], "registered": 0, "state": state}
    seen |= {"mine": mine, "answers": [mine], "kicks": 0, "kick": _Kick(0, "")}
    seen |= {"clock": _Clock(), "reads": 0, "notices": []}

    def identity():
        seen["reads"] += 1
        answers = seen["answers"]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def kickstart():
        seen["kicks"] += 1
        return seen["kick"]

    def notice(message):
        seen["notices"].append(_Notice(message))
        return seen["notices"][-1]

    def dialogs():
        state["dialogs"] += 1
        if state["fail"]:
            raise state["fail"]

    def register():
        seen["registered"] += 1
        state["status"] = "enabled"

    def browser(self, url, new=0, autoraise=True):
        seen["urls"].append(url)
        return True

    monkeypatch.setattr(deploy, "agent_status", lambda: state["status"])
    monkeypatch.setattr(deploy, "register_agent", register)
    monkeypatch.setattr(deploy, "_daemon_identity", identity)
    monkeypatch.setattr(deploy, "_wait_notice", notice)
    monkeypatch.setattr(deploy, "_kickstart", kickstart)
    monkeypatch.setattr(deploy, "time", seen["clock"])
    monkeypatch.setattr(deploy, "_request_grants_via_daemon", dialogs)
    monkeypatch.setattr(deploy, "_alert", seen["alerts"].append)
    monkeypatch.setattr(webbrowser.MacOSXOSAScript, "open", browser)
    yield seen
    deploy._DASHBOARD_KEY_FILE.unlink()
    deploy._SETUP_PENDING_FILE.unlink(missing_ok=True)


def test_first_open_installs_links_the_cli_and_lands_on_health(opened):
    opened["state"]["status"] = "not-registered"
    deploy.launch()
    assert opened["registered"] == 1 and opened["state"]["dialogs"] == 1
    assert opened["urls"][-1].endswith("&to=/health")
    assert deploy._CLI_LINK.resolve() == (deploy._APP / deploy._CLI_WRAPPER)
    assert not deploy._SETUP_PENDING_FILE.exists() and opened["alerts"] == []


def test_later_opens_go_home_without_dialogs(opened):
    deploy.launch()
    assert opened["registered"] == 0 and opened["state"]["dialogs"] == 0
    assert "&to=" not in opened["urls"][-1]


def test_a_first_open_that_failed_half_way_runs_again(opened):
    opened["state"]["status"] = "not-registered"
    opened["state"]["fail"] = NativeError("daemon socket never appeared")
    with pytest.raises(SystemExit):
        deploy.launch()
    assert "daemon socket never appeared" in opened["alerts"][-1]
    assert opened["urls"] == []
    opened["state"]["fail"] = None  # registered, but no dialogs and no Health yet
    deploy.launch()
    assert opened["registered"] == 1 and opened["state"]["dialogs"] == 2
    assert opened["urls"][-1].endswith("&to=/health")
    deploy.launch()  # done: the next open goes home
    assert opened["state"]["dialogs"] == 2 and "&to=" not in opened["urls"][-1]


def test_open_outside_applications_alerts_and_installs_nothing(opened, monkeypatch):
    monkeypatch.setattr(sys, "executable", "/private/var/T/d/x.app/Contents/MacOS/x")
    with pytest.raises(SystemExit) as e:
        deploy.launch()
    assert e.value.code == 1
    assert "/private/var/T/d/x.app" in opened["alerts"][-1]
    assert "Move it to /Applications" in opened["alerts"][-1]
    assert opened["registered"] == 0 and opened["urls"] == []
    assert not os.path.lexists(deploy._CLI_LINK)


def test_open_names_login_items_when_macos_stopped_the_agent(opened):
    opened["state"]["status"] = "requires-approval"
    with pytest.raises(SystemExit):
        deploy.launch()
    assert "Login Items" in opened["alerts"][-1] and opened["urls"] == []


def test_open_alerts_the_dashboard_refusal_and_a_missing_browser(opened, monkeypatch):
    deploy._DASHBOARD_KEY_FILE.write_text("short")  # unusable: the role exits 2
    with pytest.raises(SystemExit) as e:
        deploy.launch()
    assert e.value.code == 2 and "no usable dashboard key" in opened["alerts"][-1]
    deploy._DASHBOARD_KEY_FILE.write_text("k" * 43)
    monkeypatch.setattr(webbrowser.MacOSXOSAScript, "open", lambda *a, **kw: False)
    with pytest.raises(SystemExit) as e:
        deploy.launch()
    assert e.value.code == 1 and "No browser opened" in opened["alerts"][-1]
    assert "k" * 43 not in opened["alerts"][-1]  # the key never reaches a dialog


def test_launch_restarts_nothing_when_the_daemon_identity_is_the_bundles(opened):
    deploy.launch()
    assert opened["kicks"] == 0 and opened["state"]["dialogs"] == 0
    assert opened["notices"] == [] and opened["reads"] == 1
    assert "&to=" not in opened["urls"][-1] and opened["alerts"] == []


@pytest.mark.parametrize("other", ["version", "build", "no route"])
def test_launch_restarts_once_when_the_daemon_identity_differs(opened, other):
    """#568: launchd keeps the old daemon process after the bundle is replaced."""
    version, build = opened["mine"]
    old = {
        "version": ("0.0.1", build),
        "build": (version, "0000000 2020-01-01T00:00:00Z"),
        "no route": ("", ""),  # every daemon up to 0.16.1 answers 404
    }[other]
    # the old daemon answers twice, then the socket is dead, then the new one answers
    opened["answers"][:] = [old, old, None, opened["mine"]]
    deploy.launch()
    assert opened["kicks"] == 1 and opened["state"]["dialogs"] == 0
    assert "&to=" not in opened["urls"][-1] and opened["alerts"] == []
    [notice] = opened["notices"]  # one alert, closed when the new daemon answered
    assert (notice.ended, notice.reaped, notice.killed) == (1, 1, 0)
    assert "was restarted" in notice.message and "Waiting for" in notice.message
    assert "few minutes" in notice.message and "Reconnect" in notice.message


def test_launch_never_kickstarts_when_nothing_answers_daemon_identity(opened):
    """No answer is a daemon in its start, or none: a restart would kill the start."""
    opened["answers"][:] = [None, None, opened["mine"]]
    deploy.launch()
    assert opened["kicks"] == 0 and opened["alerts"] == []
    [notice] = opened["notices"]
    # nothing was restarted, so the text says nothing about a restart or the clients
    assert notice.ended == 1 and "Waiting for" in notice.message
    assert "restarted" not in notice.message and "Reconnect" not in notice.message
    assert "few minutes" in notice.message
    assert "&to=" not in opened["urls"][-1]


def _bound_alert(opened):
    """`launch` when the wait reaches its bound: it exits, no dashboard link was
    opened, and the one alert names Login Items and the restart command."""
    with pytest.raises(SystemExit) as e:
        deploy.launch()
    assert e.value.code == 1 and opened["urls"] == []
    [alert] = opened["alerts"]
    assert "Login Items" in alert
    assert f"launchctl kickstart -k gui/$(id -u)/{deploy.BUNDLE_ID}" in alert
    assert [n.ended for n in opened["notices"]] == [1]
    return alert


_OLD = ("0.0.1", "0000000 2020-01-01T00:00:00Z")


@pytest.mark.parametrize(
    ("other", "named"),
    [
        (_OLD, True),
        (("", ""), False),  # a daemon without the route has no identity to name
        (("9" * 41, "0000000"), False),  # too long
        (("0.0.1", "x\x1b[31m\nRun this in Terminal:"), False),  # not plain text
    ],
    ids=["plain", "no route", "long", "control characters"],
)
def test_launch_alerts_when_the_daemon_identity_never_matches(opened, other, named):
    """After the restart a daemon still answers with another identity: a copy that
    was started by hand owns the socket, or the bundle is half replaced. "It did not
    answer" would be false. Its identity comes from a socket, so the alert names it
    only when it is short plain text."""
    opened["answers"][:] = [other]
    alert = _bound_alert(opened)
    assert opened["kicks"] == 1  # never a second restart
    assert opened["clock"].now == deploy._DAEMON_WAIT == 300
    assert "Another copy" in alert and "did not answer" not in alert
    assert (f"version {other[0]}, build {other[1]}" in alert) == named
    assert ("\x1b" in alert or "9" * 41 in alert or "Run this" in alert) is False


def test_launch_alert_says_no_answer_when_the_restarted_daemon_stays_silent(opened):
    opened["answers"][:] = [_OLD, None]
    alert = _bound_alert(opened)
    assert opened["kicks"] == 1 and opened["clock"].now == 300
    assert "did not answer in time" in alert and "Another copy" not in alert


def test_launch_alerts_when_nothing_answers_daemon_identity_in_time(opened):
    opened["answers"][:] = [None]
    alert = _bound_alert(opened)
    assert opened["kicks"] == 0 and opened["clock"].now == 300
    assert "did not answer in time" in alert and "launchctl print" in alert


def test_launch_never_kickstarts_when_a_silent_socket_gives_no_daemon_identity(
    opened, sockdir, monkeypatch
):
    """`daemon.bind_socket()` listens before uvicorn serves, so a daemon in its start
    accepts the connect and stays silent. The REAL read runs here, and its read
    timeout must not read as "another daemon"."""
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    monkeypatch.setattr(deploy, "_daemon_identity", _REAL_IDENTITY)
    monkeypatch.setattr(deploy, "_IDENTITY_TIMEOUT", 0.1)
    monkeypatch.setattr(deploy, "_DAEMON_WAIT", 1.5)
    s = daemon.bind_socket(p)  # listens; nothing accepts
    try:
        _bound_alert(opened)
    finally:
        s.close()
    assert opened["kicks"] == 0


def test_wait_for_daemon_reports_a_failed_kickstart_at_once(opened):
    opened["answers"][:] = [("0.0.1", "0000000 2020-01-01T00:00:00Z")]
    opened["kick"] = _Kick(113, "Could not find service\n")
    with pytest.raises(NativeError, match="Could not find service"):
        deploy._wait_for_daemon(opened["mine"])
    assert opened["kicks"] == 1 and opened["reads"] == 1  # no read after the refusal
    # the restart comes first, so no notice claims a restart that did not happen
    assert opened["clock"].now == 0 and opened["notices"] == []
    with pytest.raises(SystemExit):
        deploy.launch()
    assert "Could not find service" in opened["alerts"][-1] and opened["urls"] == []


def test_first_open_waits_for_daemon_identity_before_the_dialogs(opened, monkeypatch):
    opened["state"]["status"] = "not-registered"
    opened["answers"][:] = [None, opened["mine"]]
    dialogs = []  # the number of identity reads at each dialog pass
    monkeypatch.setattr(
        deploy, "_request_grants_via_daemon", lambda: dialogs.append(opened["reads"])
    )
    deploy.launch()
    assert opened["registered"] == 1 and opened["kicks"] == 0
    assert dialogs == [2]  # one pass, after the daemon answered
    assert opened["urls"][-1].endswith("&to=/health") and opened["alerts"] == []
    assert not deploy._SETUP_PENDING_FILE.exists()


@pytest.mark.parametrize("first", ["not-registered", "marker"])
def test_first_open_restarts_a_daemon_of_another_identity_before_the_dialogs(
    opened, monkeypatch, first
):
    """A first open (or one that failed half-way) can meet an old daemon too: it must
    compare, not take any answer."""
    if first == "marker":
        deploy._SETUP_PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        deploy._SETUP_PENDING_FILE.touch()
    else:
        opened["state"]["status"] = "not-registered"
    opened["answers"][:] = [_OLD, None, opened["mine"]]
    dialogs = []  # the number of identity reads at each dialog pass
    monkeypatch.setattr(
        deploy, "_request_grants_via_daemon", lambda: dialogs.append(opened["reads"])
    )
    deploy.launch()
    assert opened["kicks"] == 1
    assert dialogs == [3]  # one pass, after the NEW daemon answered
    assert opened["urls"][-1].endswith("&to=/health") and opened["alerts"] == []


def test_wait_for_daemon_goes_on_when_the_notice_cannot_start(opened, monkeypatch):
    """The notice is optional: a child that cannot start must not stop the restart."""

    def no_child(message):
        raise OSError("osascript: cannot start")

    monkeypatch.setattr(deploy, "_wait_notice", no_child)
    opened["answers"][:] = [_OLD, None, opened["mine"]]
    deploy.launch()
    assert opened["kicks"] == 1 and opened["alerts"] == []
    assert "&to=" not in opened["urls"][-1]


def test_wait_for_daemon_kills_a_notice_that_does_not_end(opened, monkeypatch):
    """No zombie stays, and a child that ignores the signal cannot block the exit."""
    monkeypatch.setattr(_Notice, "stuck", True)
    opened["answers"][:] = [None, opened["mine"]]
    deploy._wait_for_daemon(opened["mine"])
    [notice] = opened["notices"]
    assert (notice.ended, notice.reaped, notice.killed) == (1, 0, 1)


def test_wait_for_daemon_needs_an_answer_not_a_socket_file(
    opened, sockdir, monkeypatch
):
    """A killed daemon leaves its socket file: the old wait returned on it, and the
    dashboard opened on a dead port. The REAL read runs here."""
    p = sockdir / "mcp.sock"
    p.touch()
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    monkeypatch.setattr(deploy, "_daemon_identity", _REAL_IDENTITY)
    monkeypatch.setattr(deploy, "_DAEMON_WAIT", 5)  # each real read costs about 30 ms
    for want in (opened["mine"], None):  # the `launch` mode and the any-answer mode
        opened["clock"].now = 0
        # `install-agent` keeps its old advice beside the new one
        with pytest.raises(NativeError, match="Login Items") as e:
            deploy._wait_for_daemon(want)
        assert "launchctl print" in str(e.value) and "logs" in str(e.value)
        assert opened["clock"].now == 5 and opened["kicks"] == 0


def test_wait_for_daemon_takes_any_answer_without_a_kickstart(opened, capsys):
    """The `install-agent` mode: its caller can be another Python than the bundle, so
    it compares nothing and restarts nothing."""
    opened["answers"][:] = [None, ("", "")]
    deploy._wait_for_daemon()
    assert opened["kicks"] == 0 and opened["notices"] == [] and opened["reads"] == 2
    err = capsys.readouterr().err
    assert "few minutes" in err and "up to 300 s" in err and err.count("\n") == 1


def test_wait_notice_carries_its_text_as_an_argument_and_ends_by_itself(monkeypatch):
    started = []
    monkeypatch.setattr(
        deploy.subprocess, "Popen", lambda argv, **kw: started.append(argv) or "child"
    )
    text = 'updated" & (do shell script "id") & "'
    assert deploy._wait_notice(text) == "child"  # returns at once, with the child
    [argv] = started
    assert argv[0] == "osascript" and argv[-1] == text
    script = "\n".join(argv[1:-1])
    assert "do shell script" not in script and "updated" not in script
    assert "display alert" in script and "as critical" not in script
    # a lost parent leaves no dialog for ever
    assert f"giving up after {deploy._DAEMON_WAIT + 10}" in script


def test_wait_for_daemon_ends_the_notice_on_every_exit(opened):
    opened["answers"][:] = [None, opened["mine"]]
    deploy._wait_for_daemon(opened["mine"])  # it returns
    opened["answers"][:] = [None]
    with pytest.raises(NativeError):
        deploy._wait_for_daemon(opened["mine"])  # it raises at the bound
    assert [(n.ended, n.reaped) for n in opened["notices"]] == [(1, 1), (1, 1)]


def test_kickstart_helper_runs_the_one_launchctl_restart(monkeypatch):
    ran = []
    monkeypatch.setattr(
        deploy.subprocess, "run", lambda argv, **kw: ran.append(argv) or _Kick(0, "")
    )
    assert deploy._kickstart().returncode == 0
    target = f"gui/{os.getuid()}/{deploy.BUNDLE_ID}"
    assert ran == [["launchctl", "kickstart", "-k", target]]


def test_allow_send_uses_the_kickstart_helper(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "_ALLOW_SEND_FILE", tmp_path / "state" / "allow_send")
    kicks = [_Kick(0, ""), _Kick(1, "not registered\n")]
    monkeypatch.setattr(deploy, "_kickstart", lambda: kicks.pop(0))
    deploy.allow_send(["mail"])
    assert capsys.readouterr().out == (
        "outbound: mail\ndaemon restarted — reconnect your MCP client\n"
    )
    deploy.allow_send(["off"])
    assert capsys.readouterr().out == (
        "outbound: off\nno daemon restarted (not registered); restart your "
        "stdio server for this to take effect\n"
    )
    assert kicks == []  # one restart for each change


def test_allow_send_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "_ALLOW_SEND_FILE", tmp_path / "state" / "allow_send")
    monkeypatch.setattr(
        deploy.subprocess, "run", lambda *a, **k: _Kick(1, "not registered")
    )
    deploy.allow_send([])
    assert capsys.readouterr().out.strip() == "off"
    deploy.allow_send(["mail"])
    assert "outbound: mail" in capsys.readouterr().out
    deploy.allow_send([])
    assert capsys.readouterr().out.strip() == "mail"
    deploy.allow_send(["off"])
    assert "outbound: off" in capsys.readouterr().out
    assert deploy.allow_send_file() == ""


class _Kick:
    def __init__(self, returncode, stderr):
        self.returncode, self.stderr = returncode, stderr


def test_allow_send_gate_ignores_xdg_state_home(tmp_path):
    """The consent gate must NOT move with $XDG_STATE_HOME — otherwise it fails OPEN.

    An operator with XDG_STATE_HOME exported runs `macos-apps-mcp allow-send off`; the
    write and the confirming read both land in the XDG dir while the launchd daemon
    (which has no shell env at all) keeps reading the home path and keeps
    send_mail/reply_all/forward_mail registered. Asserted in a SUBPROCESS because the
    constant is bound at import and the suite monkeypatches it for isolation.
    """
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from macos_apps_mcp import deploy; print(deploy._ALLOW_SEND_FILE)",
        ],
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == str(Path.home() / ".local/state/macos-apps-mcp/allow_send")


def test_allow_send_file_reaches_the_gate_only_under_the_daemon(tmp_path, monkeypatch):
    """The persisted toggle exists because env cannot reach the launchd daemon — a
    stdio server (and every test run) must stay driven by the env var alone."""
    from macos_apps_mcp import tiers

    monkeypatch.setattr(deploy, "_ALLOW_SEND_FILE", tmp_path / "allow_send")
    (tmp_path / "allow_send").write_text("mail")
    monkeypatch.delenv("MACOS_APPS_ALLOW_SEND", raising=False)
    monkeypatch.delenv("MACOS_APPS_READ_ONLY", raising=False)

    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    assert tiers.allow_send("mail") is False

    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    assert tiers.allow_send("mail") is True

    # READ_ONLY still wins unconditionally (#104)
    monkeypatch.setenv("MACOS_APPS_READ_ONLY", "1")
    assert tiers.allow_send("mail") is False


# --- #318: the grant map names the denial reason and the AppleEvents target --------

_ME = "ren.lav.macos-apps-mcp"


def _entries(tmp_path, monkeypatch, rows, service):
    db = tmp_path / "TCC.db"
    _tcc_db(db, rows)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    monkeypatch.setattr(deploy, "_TCC_SYSTEM_DB", tmp_path / "absent" / "TCC.db")
    return deploy.grant_identities([service])[service]


def test_timed_out_prompt_is_prompt_timeout_with_remediation(tmp_path, monkeypatch):
    # #318: reason 9 is a prompt nobody answered; it must say so and name the way out.
    svc = "kTCCServiceAppleEvents"
    (entry,) = _entries(
        tmp_path, monkeypatch, [(svc, _ME, 0, 9, "com.apple.mail")], svc
    )
    assert entry["client"] == _ME and entry["target"] == "com.apple.mail"
    assert entry["granted"] is False and entry["reason"] == "prompt-timeout"
    assert entry["remediation"] == f"tccutil reset AppleEvents {_ME}"


def test_remediation_names_the_rows_own_service(tmp_path, monkeypatch):
    # #318: never `All`; the command resets the one service the row is about.
    svc = "kTCCServiceCalendar"
    (entry,) = _entries(tmp_path, monkeypatch, [(svc, _ME, 0, 9, "UNUSED")], svc)
    assert f"tccutil reset Calendar {_ME}" in entry["remediation"]


def test_user_denial_has_reason_and_no_remediation(tmp_path, monkeypatch):
    # #318
    svc = "kTCCServiceAppleEvents"
    out = _entries(tmp_path, monkeypatch, [(svc, _ME, 0, 2, "com.apple.Notes")], svc)
    assert out == [
        {
            "client": _ME,
            "target": "com.apple.Notes",
            "granted": False,
            "reason": "user-consent",
        }
    ]


def test_unknown_denial_reason(tmp_path, monkeypatch):
    # #318
    svc = "kTCCServiceCalendar"
    (entry,) = _entries(tmp_path, monkeypatch, [(svc, _ME, 0, 42, "UNUSED")], svc)
    assert entry["reason"] == "unknown(42)" and "remediation" not in entry


def test_granted_entry_carries_target_not_reason(tmp_path, monkeypatch):
    # #318
    svc = "kTCCServiceAppleEvents"
    out = _entries(tmp_path, monkeypatch, [(svc, _ME, 2, 3, "com.apple.Photos")], svc)
    assert out == [{"client": _ME, "target": "com.apple.Photos", "granted": True}]


@pytest.mark.parametrize("target", [None, "", "UNUSED"])
def test_no_real_target_means_no_target_key(tmp_path, monkeypatch, target):
    # #318
    svc = "kTCCServiceCalendar"
    out = _entries(tmp_path, monkeypatch, [(svc, _ME, 2, 2, target)], svc)
    assert out == [{"client": _ME, "granted": True}]


@pytest.mark.parametrize("dropped", ["auth_reason", "indirect_object_identifier"])
def test_tcc_rows_missing_new_column_is_schema_drift(tmp_path, dropped):
    # #318: both new columns are fingerprinted; an older table reads schema-drift.
    cols = {
        "service",
        "client",
        "auth_value",
        "auth_reason",
        "indirect_object_identifier",
    } - {dropped}
    db = tmp_path / "TCC.db"
    c = sqlite3.connect(db)
    c.execute(f"CREATE TABLE access ({', '.join(sorted(cols))})")
    c.commit()
    c.close()
    assert deploy._tcc_rows(db, ["kTCCServiceCalendar"]) == (None, "schema-drift")
