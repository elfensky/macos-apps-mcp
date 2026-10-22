"""The loopback guard and the ASGI dispatcher (PLAT-02, D-06, D-07): no sockets served,
no port held. Dispatcher cases use hand-built scopes and recording stub apps."""

import asyncio
import socket

import pytest

from macos_apps_mcp import daemon


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "localhost", "::", ""])
def test_assert_loopback_refuses_everything_but_a_loopback_literal(host):
    with pytest.raises(ValueError, match="not a loopback address"):
        daemon.assert_loopback(host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_assert_loopback_accepts_loopback_literals(host):
    assert daemon.assert_loopback(host) == host


def test_bind_dashboard_refuses_before_binding_anything(monkeypatch):
    def no_socket(*a, **kw):
        raise AssertionError("a socket was created for a non-loopback host")

    monkeypatch.setattr(socket, "socket", no_socket)
    with pytest.raises(ValueError):
        daemon.bind_dashboard("0.0.0.0", 0)


def test_bind_dashboard_loopback_returns_a_listening_socket():
    s = daemon.bind_dashboard("127.0.0.1", 0)
    try:
        host, port = s.getsockname()
        assert host == "127.0.0.1" and port > 0
        probe = socket.create_connection((host, port), timeout=2)  # listen() was called
        probe.close()
    finally:
        s.close()


def _stub(name, log):
    async def app(scope, receive, send):
        log.append(name)

    return app


def _dispatch(scope, dash=True):
    log: list[str] = []
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    dispatcher = daemon.make_dispatcher(
        _stub("mcp", log), _stub("dash", log) if dash else None
    )
    asyncio.run(dispatcher(scope, None, send))
    return log, sent


@pytest.mark.parametrize(
    ("scope", "want"),
    [
        ({"type": "lifespan"}, ["mcp"]),
        ({"type": "http", "server": ("/x/mcp.sock", None)}, ["mcp"]),
        ({"type": "http", "server": ["/x/mcp.sock", None]}, ["mcp"]),
        ({"type": "http", "server": ("127.0.0.1", 47632)}, ["dash"]),
        ({"type": "http", "server": None}, ["dash"]),  # C4: fail closed
        ({"type": "http"}, ["dash"]),
        ({"type": "http", "server": ("127.0.0.1",)}, ["dash"]),
        ({"type": "websocket", "server": ("/x/mcp.sock", None)}, []),
    ],
)
def test_dispatcher_routes_mcp_to_the_unix_socket_only(scope, want):
    assert _dispatch(scope)[0] == want


def test_dispatcher_without_a_dashboard_answers_404_and_never_reaches_mcp():
    log, sent = _dispatch({"type": "http", "server": ("127.0.0.1", 47632)}, dash=False)
    assert log == []
    assert sent[0]["status"] == 404
