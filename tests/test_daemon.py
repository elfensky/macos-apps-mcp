import asyncio
import os
import re
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import FastMCPProxy
from mcp.types import Implementation

import macos_apps_mcp
from macos_apps_mcp import audit as au
from macos_apps_mcp import daemon, deploy, registry


@pytest.fixture(autouse=True)
def _no_role_leak():
    """daemon.serve() sets MACOS_APPS_MCP_ROLE=daemon as its first act (before the
    server import), and test_serve_two_concurrent_sessions runs it in a daemon=True
    background thread. monkeypatch can't undo a write made by another thread after
    the test function returns, so without this the role leaks into every later test
    in the process (#141). Restore directly via os.environ regardless of what the
    thread did."""
    original = os.environ.get("MACOS_APPS_MCP_ROLE")
    yield
    if original is None:
        os.environ.pop("MACOS_APPS_MCP_ROLE", None)
    else:
        os.environ["MACOS_APPS_MCP_ROLE"] = original


@pytest.fixture(autouse=True)
def _no_real_dashboard_port(monkeypatch):
    """daemon.serve() binds the dashboard on daemon.DASHBOARD_PORT (47632). The
    two-session test runs the real serve() in a thread that never exits, so without
    port 0 a unit test would hold the real port for the whole session and collide
    with an installed daemon (RESEARCH C6)."""
    monkeypatch.setattr(daemon, "DASHBOARD_PORT", 0)


@pytest.fixture
def sockdir():
    # AF_UNIX sun_path is ~104 bytes on macOS; pytest's default tmp_path nesting
    # exceeds it. mkdtemp at the tmp root keeps paths ~50 chars — daemon tests only.
    d = Path(tempfile.mkdtemp(prefix="mcpsock-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_socket_path_env_override(sockdir, monkeypatch):
    p = sockdir / "s.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert daemon.socket_path() == p


def test_socket_path_default_ignores_xdg_state_home(tmp_path, monkeypatch):
    # launchd agents don't inherit shell exports — the daemon (launchd), install-agent
    # (shell), and a client-spawned shim must all rendezvous at the SAME default path
    # regardless of what any one of them has in XDG_STATE_HOME.
    monkeypatch.delenv("MACOS_APPS_MCP_SOCKET", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    expected = (
        Path.home() / ".local" / "state" / "macos-apps-mcp" / "daemon" / "mcp.sock"
    )
    assert daemon.socket_path() == expected


def test_bind_socket_perms(sockdir):
    p = sockdir / "d" / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    finally:
        s.close()


def test_bind_socket_live_owner_raises(sockdir):
    p = sockdir / "mcp.sock"
    s1 = daemon.bind_socket(p)
    try:
        with pytest.raises(daemon.AlreadyRunning):
            daemon.bind_socket(p)
    finally:
        s1.close()


def test_bind_socket_stale_file_rebinds(sockdir):
    p = sockdir / "mcp.sock"
    daemon.bind_socket(p).close()  # closed listener leaves a stale file
    assert p.exists()
    s = daemon.bind_socket(p)  # ECONNREFUSED probe → unlink → rebind
    try:
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(p))  # proves it is live again
        c.close()
    finally:
        s.close()


def test_serve_two_concurrent_sessions(sockdir, monkeypatch, capfd):
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    monkeypatch.setattr(daemon, "dashboard_state", None)
    t = threading.Thread(target=daemon.serve, daemon=True)
    t.start()
    for _ in range(100):  # wait for the socket
        if p.exists():
            break
        time.sleep(0.05)

    async def go():
        def transport():
            return StreamableHttpTransport(
                "http://daemon/mcp",
                httpx_client_factory=daemon._uds_client_factory(p),
            )

        async with Client(transport()) as c1, Client(transport()) as c2:
            r1, r2 = await asyncio.gather(c1.call_tool("ping"), c2.call_tool("ping"))
            assert "ok" in r1.content[0].text and "ok" in r2.content[0].text

    asyncio.run(go())

    # The same Server also answers on loopback TCP: dashboard only, never MCP.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not str(daemon.dashboard_state).startswith(
        "http://127.0.0.1:"
    ):
        time.sleep(0.05)
    base = daemon.dashboard_state
    assert str(base).startswith("http://127.0.0.1:"), base
    # D-19: the daemon wrote the page key (0600 file, 0700 folder) and every request
    # but the link needs it as a cookie.
    key_file = deploy._DASHBOARD_KEY_FILE
    key = key_file.read_text()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", key)
    cookie = {"cookie": f"macos_apps_mcp_key={key}"}
    with httpx.Client(trust_env=False, timeout=10) as web:
        refused = web.get(f"{base}/usage")
        assert refused.status_code == 403
        assert "macos-apps-mcp dashboard" in refused.text
        assert "content-security-policy" in refused.headers
        link = web.get(f"{base}/key", params={"k": key})
        assert link.status_code == 303 and link.headers["location"] == "/"
        set_cookie = link.headers["set-cookie"]
        assert f"macos_apps_mcp_key={key}" in set_cookie
        assert "HttpOnly" in set_cookie and "SameSite=strict" in set_cookie
        assert "Path=/" in set_cookie
        usage = web.get(f"{base}/usage", headers=cookie)
        assert usage.status_code == 200
        assert "Calls per tool since the log started." in usage.text
        assert "content-security-policy" in usage.headers
        assert usage.headers["referrer-policy"] == "same-origin"
        # no Origin: the Guard refuses
        unsigned = web.post(f"{base}/mcp", json={}, headers=cookie)
        assert unsigned.status_code == 403
        assert "Forbidden origin" in unsigned.text
        get_mcp = web.get(f"{base}/mcp", headers=cookie)
        assert get_mcp.status_code == 404
        assert "jsonrpc" not in unsigned.text + get_mcp.text
    out, err = capfd.readouterr()
    assert key not in out + err  # access_log=False: the link's query never prints


def test_serve_keeps_mcp_up_when_the_dashboard_port_is_in_use(sockdir, monkeypatch):
    """T-05-13: a taken dashboard port is logged, `dashboard_state` says so, and MCP
    over the unix socket keeps serving."""
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    monkeypatch.setattr(daemon, "DASHBOARD_PORT", taken.getsockname()[1])
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    threading.Thread(target=daemon.serve, daemon=True).start()
    for _ in range(100):
        if p.exists():
            break
        time.sleep(0.05)

    async def go():
        transport = StreamableHttpTransport(
            "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
        )
        async with Client(transport) as c:
            return await c.call_tool("ping")

    try:
        assert "ok" in asyncio.run(go()).content[0].text
        state = str(daemon.dashboard_state)
        assert state.startswith("not bound: ")
        assert "\n" not in state
        assert "\r" not in state
    finally:
        taken.close()


def _serve_and_ping(p) -> str:
    """Start daemon.serve in a thread, wait for the socket, return the ping text."""
    threading.Thread(target=daemon.serve, daemon=True).start()
    for _ in range(100):
        if p.exists():
            break
        time.sleep(0.05)

    async def go():
        transport = StreamableHttpTransport(
            "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
        )
        async with Client(transport) as c:
            return await c.call_tool("ping")

    return asyncio.run(go()).content[0].text


def _break_build(monkeypatch, exc):
    def boom(**_kw):
        raise exc

    monkeypatch.setattr("macos_apps_mcp.dashboard.build_app", boom)


def _break_import(monkeypatch):
    monkeypatch.delattr(macos_apps_mcp, "dashboard", raising=False)
    monkeypatch.setitem(sys.modules, "macos_apps_mcp.dashboard", None)


@pytest.mark.parametrize("failure", ["build", "import"])
def test_serve_keeps_mcp_up_when_the_dashboard_cannot_be_built(
    sockdir, monkeypatch, failure
):
    """WR-05 (D-07): a dashboard import or build fault is logged, named in
    `dashboard_state`, frees the TCP socket, and MCP keeps serving."""
    if failure == "build":
        _break_build(monkeypatch, RuntimeError("x" * 500))
    else:
        _break_import(monkeypatch)
    bound = []
    real_bind = daemon.bind_dashboard

    def recorder(host, port):
        bound.append(real_bind(host, port))
        return bound[-1]

    monkeypatch.setattr(daemon, "bind_dashboard", recorder)
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert "ok" in _serve_and_ping(p)
    state = daemon.dashboard_state
    assert state.startswith("not built: "), state
    assert "http://" not in state
    assert len(state) <= len("not built: ") + daemon.NOT_BUILT_MAX
    assert len(bound) == 1 and bound[0].fileno() == -1


def test_dashboard_not_built_names_the_exception_type_when_its_message_is_empty(
    sockdir, monkeypatch
):
    _break_build(monkeypatch, RuntimeError())
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert "ok" in _serve_and_ping(p)
    assert daemon.dashboard_state == "not built: RuntimeError"


def test_dashboard_not_built_names_the_exception_type_when_its_message_is_blank(
    sockdir, monkeypatch
):
    _break_build(monkeypatch, RuntimeError("   "))
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert "ok" in _serve_and_ping(p)
    assert daemon.dashboard_state == "not built: RuntimeError"


def test_dashboard_not_built_state_is_one_sanitized_line(sockdir, monkeypatch):
    _break_build(monkeypatch, RuntimeError('first\nsecond "q" \\ café'))
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert "ok" in _serve_and_ping(p)
    state = daemon.dashboard_state
    assert "\n" not in state and "\r" not in state, state
    assert state.startswith("not built: first second"), state


def test_serve_reports_no_url_when_the_page_key_is_unusable(sockdir, monkeypatch):
    """IN-04: every page answers 503, so doctor must not name a URL."""
    monkeypatch.setattr(deploy, "dashboard_key", lambda create=False: None)
    monkeypatch.setattr(daemon, "dashboard_state", None)
    p = sockdir / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert "ok" in _serve_and_ping(p)
    state = daemon.dashboard_state
    assert state == daemon.KEY_UNUSABLE_STATE
    assert "http://" not in state


def _serve(app, path):
    """Serve `app` over a UDS the way daemon.serve() does; returns the listener."""
    s = daemon.bind_socket(path)
    config = uvicorn.Config(
        app.http_app(), fd=s.fileno(), log_level="warning", ws="none"
    )
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()
    for _ in range(100):
        if path.exists():
            break
        time.sleep(0.05)
    return s


def test_slow_tool_returns_over_the_socket(sockdir):
    """#170: httpx's DEFAULT Timeout(5.0) applied to the response SSE stream, so a
    tool call taking longer than 5s never came back — the daemon did the work, the
    shim gave up reading, and the swallowed ReadTimeout (see the test below) turned
    that into a 1800s client hang. Device-confirmed cliff: 4.5s returned, 6s did not.
    This call MUST exceed 5s to fail on the old behaviour."""
    app = FastMCP("slowtest")

    @app.tool
    def slow() -> dict:
        time.sleep(6)  # > the old 5s cliff; a real bulk Mail pass runs for HOURS
        return {"ok": True}

    p = sockdir / "mcp.sock"
    s = _serve(app, p)

    async def go():
        async with Client(
            StreamableHttpTransport(
                "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
            )
        ) as c:
            return await asyncio.wait_for(c.call_tool("slow"), timeout=60)

    try:
        assert "ok" in asyncio.run(go()).content[0].text
    finally:
        s.close()


def test_dead_response_stream_errors_instead_of_hanging(sockdir):
    """#170 second bug: mcp swallows any error on a request's SSE stream and returns
    without answering, so the request hangs forever instead of failing. Simulated with
    a deliberately tiny client timeout — on the old behaviour this never returns."""
    daemon.fail_loud_on_dead_stream()
    app = FastMCP("deadtest")

    @app.tool
    def slow() -> dict:
        time.sleep(3)
        return {"ok": True}

    p = sockdir / "mcp.sock"
    s = _serve(app, p)

    def impatient(**kwargs):  # 0.5s read deadline → the stream dies mid-call
        kwargs.pop("transport", None)
        kwargs["timeout"] = httpx.Timeout(0.5)
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(p)), **kwargs
        )

    async def go():
        async with Client(
            StreamableHttpTransport("http://daemon/mcp", httpx_client_factory=impatient)
        ) as c:
            await asyncio.wait_for(c.call_tool("slow"), timeout=30)

    try:
        with pytest.raises(Exception) as e:  # noqa: B017 — the point is *anything* loud
            asyncio.run(go())
        assert not isinstance(e.value, TimeoutError), "hung instead of erroring"
        assert "ended without a result" in str(e.value)
    finally:
        s.close()


def test_shim_check_absent_socket_exits_2(sockdir):
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(sockdir / "missing.sock")
    assert e.value.code == 2


def test_shim_check_stale_socket_exits_2(sockdir):
    p = sockdir / "mcp.sock"
    daemon.bind_socket(p).close()  # stale file, nobody listening
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(p)
    assert e.value.code == 2


def test_shim_check_live_socket_passes(sockdir):
    p = sockdir / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        daemon.shim_check(p)  # no raise
    finally:
        s.close()


# --- #302: anyio's cancelled-wait InvalidStateError on UDS client loops -----------


@pytest.fixture
def rec_loop():
    """A fresh loop whose default exception handler records instead of logging; a
    custom handler is NOT set, so the factory still sees `get_exception_handler()`
    as None (#302)."""
    loop = asyncio.new_event_loop()
    seen: list[dict] = []
    loop.default_exception_handler = seen.append
    try:
        yield loop, seen
    finally:
        loop.close()


def _turn(loop, *calls):
    """Queue each (fn, *args) with call_soon, then run the loop for one turn."""
    for fn, *args in calls:
        loop.call_soon(fn, *args)
    loop.call_soon(loop.stop)
    loop.run_forever()


def test_cancelled_wait_race_is_dropped(rec_loop):
    """#302: set_result queued on a future cancelled in the same turn is logged by
    asyncio (the reproduction is real) and dropped by the handler."""
    loop, seen = rec_loop
    f = loop.create_future()
    f.cancel()
    _turn(loop, (f.set_result, None))
    assert len(seen) == 1
    assert isinstance(seen[0]["exception"], asyncio.InvalidStateError)

    seen.clear()
    loop.set_exception_handler(daemon._drop_cancelled_wait)
    g = loop.create_future()
    g.cancel()
    _turn(loop, (g.set_result, None))
    assert seen == []


@pytest.mark.parametrize("case", ["set_result_on_done", "set_exception_on_cancelled"])
def test_other_invalid_state_errors_still_log(rec_loop, case):
    """#302: only set_result on a CANCELLED future is dropped; the same
    InvalidStateError from any other handle reaches the default handler."""
    loop, seen = rec_loop
    loop.set_exception_handler(daemon._drop_cancelled_wait)
    f = loop.create_future()
    if case == "set_result_on_done":
        f.set_result(1)
        _turn(loop, (f.set_result, None))
    else:
        f.cancel()
        _turn(loop, (f.set_exception, ValueError()))
    assert len(seen) == 1
    assert isinstance(seen[0]["exception"], asyncio.InvalidStateError)


@pytest.mark.parametrize("case", ["other_exception_type", "no_handle"])
def test_crafted_contexts_pass_through(rec_loop, case):
    """#302: a non-InvalidStateError, or a context without a handle, is passed on as
    the identical dict."""
    loop, seen = rec_loop
    f = loop.create_future()
    f.cancel()
    if case == "other_exception_type":
        ctx = {
            "message": "boom",
            "exception": ValueError(),
            "handle": loop.call_soon(f.set_result, None),
        }
    else:
        ctx = {"message": "boom", "exception": asyncio.InvalidStateError()}
    daemon._drop_cancelled_wait(loop, ctx)
    assert len(seen) == 1
    assert seen[0] is ctx


def test_factory_installs_the_handler_once_per_loop(sockdir):
    """#302: the factory installs `_drop_cancelled_wait` on the running loop, and
    repeated calls leave it in place."""

    async def go():
        loop = asyncio.get_running_loop()
        assert loop.get_exception_handler() is None
        factory = daemon._uds_client_factory(sockdir / "s.sock")
        first = factory()
        second = factory()
        got = loop.get_exception_handler()
        await first.aclose()
        await second.aclose()
        return got

    assert asyncio.run(go()) is daemon._drop_cancelled_wait


def test_factory_keeps_an_existing_handler(sockdir):
    """#302: a handler the host already set on the loop is never replaced."""

    def mine(loop, context):  # pragma: no cover - never invoked
        pass

    assert mine is not daemon._drop_cancelled_wait

    async def go():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(mine)
        client = daemon._uds_client_factory(sockdir / "s.sock")()
        got = loop.get_exception_handler()
        await client.aclose()
        return got

    assert asyncio.run(go()) is mine


def test_factory_without_a_running_loop_still_builds_the_client(sockdir):
    """#302: no running loop means nothing to install on; the client is returned."""
    client = daemon._uds_client_factory(sockdir / "s.sock")()
    assert isinstance(client, httpx.AsyncClient)


def test_shim_forwards_client_and_records_resolved_dry_run(sockdir, monkeypatch):
    """#222 tracer: front client -> FastMCPProxy(shim client factory) -> real unix
    socket -> daemon-side AuditMiddleware. The record names the REAL client (not the
    daemon's `mcp 0.1.0`), carries the shim id, and states the resolved dry_run."""

    def delete_x(id: str, dry_run: bool = True) -> dict:
        return {"id": id, "dry_run": dry_run}

    records: list[dict] = []
    monkeypatch.setattr(au, "audit_write", records.append)
    monkeypatch.setattr(au, "usage_log", lambda tool: None)
    app = FastMCP("t")
    app.add_middleware(
        au.AuditMiddleware(
            audit_verbs={"delete_x": "delete"},
            snapshot_sources={},
            dry_run_defaults={"delete_x": registry._dry_run_default(delete_x)},
        )
    )
    app.tool(delete_x)
    p = sockdir / "mcp.sock"
    s = _serve(app, p)
    transport = StreamableHttpTransport(
        "http://daemon/mcp", httpx_client_factory=daemon._uds_client_factory(p)
    )
    proxy = FastMCPProxy(
        client_factory=daemon._shim_client_factory(transport, "abc12345")
    )

    async def go():
        async with Client(
            proxy, client_info=Implementation(name="claude-code", version="2.1.9")
        ) as c:
            await asyncio.wait_for(c.call_tool("delete_x", {"id": "A"}), timeout=30)
            await asyncio.wait_for(
                c.call_tool("delete_x", {"id": "B", "dry_run": "false"}), timeout=30
            )

    try:
        asyncio.run(go())
    finally:
        s.close()
    assert len(records) == 2
    first, second = records
    assert first["op"] == "delete" and first["args"] == {"id": "A"}
    assert first["dry_run"] is True
    assert first["caller"] == "claude-code 2.1.9" and first["session"] == "abc12345"
    assert second["args"] == {"id": "B", "dry_run": "false"}
    assert second["dry_run"] is False
    assert second["caller"] == "claude-code 2.1.9"


def _factory_calls(monkeypatch, get_context, shim_id="abc12345", n=1):
    """Drive `_shim_client_factory` with `daemon.get_context` and `daemon._Client`
    patched; returns the `client_info` of each client the factory built."""
    seen = []
    monkeypatch.setattr(daemon, "get_context", get_context)
    monkeypatch.setattr(
        daemon, "_Client", lambda transport, client_info: seen.append(client_info)
    )
    f = daemon._shim_client_factory(object(), shim_id)
    for _ in range(n):
        f()
    return seen


def _context_with(client_params):
    return lambda: SimpleNamespace(session=SimpleNamespace(client_params=client_params))


def test_shim_client_factory_copies_the_client_info(monkeypatch):
    params = SimpleNamespace(
        clientInfo=Implementation(name="claude-code", version="2.1.9")
    )
    (info,) = _factory_calls(monkeypatch, _context_with(params))
    assert (info.name, info.version) == ("claude-code", "2.1.9")
    assert info.session == "abc12345"


def test_shim_client_factory_initialize_path_uses_the_shim_identity(monkeypatch):
    # proxy.py:90 — initialize runs before the front session stores client_params
    (info,) = _factory_calls(monkeypatch, _context_with(None))
    assert (info.name, info.version) == ("macos-apps-mcp-shim", "0")
    assert info.session == "abc12345"


def test_shim_client_factory_ping_path_uses_the_shim_identity(monkeypatch):
    # proxy.py:921 — ping_remote runs outside a request, so get_context() raises
    def no_context():
        raise RuntimeError("No active context found.")

    (info,) = _factory_calls(monkeypatch, no_context)
    assert (info.name, info.version) == ("macos-apps-mcp-shim", "0")
    assert info.session == "abc12345"


def test_shim_client_factory_session_is_stable_per_factory(monkeypatch):
    first, second = _factory_calls(monkeypatch, _context_with(None), n=2)
    assert first.session == second.session == "abc12345"
    (other,) = _factory_calls(monkeypatch, _context_with(None), shim_id="def67890")
    assert other.session == "def67890"
