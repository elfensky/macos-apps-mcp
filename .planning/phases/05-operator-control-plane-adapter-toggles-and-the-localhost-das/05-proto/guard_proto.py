"""Seed for the dashboard's request checks (D-08, amended: Referrer-Policy same-origin).
Pure ASGI, no third-party code. Exercised by guard_probe.py through httpx.ASGITransport.
Throwaway proto: the executor ports this into macos_apps_mcp/dashboard.py."""

from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import parse_qs

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; frame-ancestors 'none'; form-action 'self'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    # NOT no-referrer: Chrome 155 sends `Origin: null` on a same-origin form POST then.
    (b"referrer-policy", b"same-origin"),
    (b"cache-control", b"no-store"),
]
MAX_BODY = 8 * 1024


def assert_loopback(host: str) -> str:
    """Raise unless ``host`` is a literal loopback IP ('localhost' is refused too:
    it is a name, and a name can be re-pointed)."""
    if not ipaddress.ip_address(host).is_loopback:  # ValueError for a non-IP
        raise ValueError(f"dashboard refuses to bind {host!r}: not a loopback address")
    return host


class Guard:
    def __init__(self, app: ASGIApp, port: int, token: str) -> None:
        self.app, self.token = app, token
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        h = {k.decode("latin1"): v.decode("latin1") for k, v in scope["headers"]}

        async def send_h(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), *HEADERS]}
            await send(msg)

        deny = None
        if h.get("host") not in self.hosts:  # reads too: DNS rebinding
            deny = PlainTextResponse("Invalid host header", 400)
        elif scope["method"] == "POST":
            origin = h.get("origin")
            same = (origin in self.origins) if origin is not None else (
                h.get("sec-fetch-site") == "same-origin")  # Origin: null -> False
            if not same:
                deny = PlainTextResponse("Forbidden origin", 403)
            else:  # token: urlencoded body, no python-multipart
                body = b""
                while True:
                    m = await receive()
                    body += m.get("body", b"")
                    if len(body) > MAX_BODY:
                        break
                    if not m.get("more_body"):
                        break
                got = parse_qs(body.decode("utf-8", "replace")).get("token", [""])[0]
                if len(body) > MAX_BODY or not hmac.compare_digest(
                    got.encode(), self.token.encode()
                ):
                    deny = PlainTextResponse("Forbidden token", 403)
                else:
                    replayed = False

                    async def receive_again() -> Message:
                        nonlocal replayed
                        if not replayed:
                            replayed = True
                            return {"type": "http.request", "body": body}
                        return await receive()

                    return await self.app(scope, receive_again, send_h)
        if deny is not None:
            return await deny(scope, receive, send_h)
        return await self.app(scope, receive, send_h)
