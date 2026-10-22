"""The request layer of the localhost dashboard (PLAT-02, D-08).

A loopback bind keeps other machines out; it does not keep other WEBSITES out. Any page
in the operator's browser can POST to 127.0.0.1 (CSRF), and DNS rebinding lets a remote
page read loopback responses. So every request passes this pure-ASGI wrapper first:

* ``Host`` must be ``127.0.0.1:<port>`` or ``localhost:<port>`` on EVERY request, reads
  included (DNS rebinding).
* A POST (any method but GET and HEAD, so a later PUT or DELETE route is born
  guarded) needs ``Origin`` equal to one of those origins; with no ``Origin`` it needs
  ``Sec-Fetch-Site: same-origin``. ``Origin: null`` is foreign (RESEARCH C1: Chrome
  sends it on a same-origin form POST under ``Referrer-Policy: no-referrer``, so the
  headers below use ``same-origin``).
* A POST also needs the per-session token from the urlencoded body, compared in
  constant time, under an 8 KiB body cap (RESEARCH C8: no multipart parser).
* Every response carries the security headers, refusals included.

The body is read here and replayed to the app, so a handler still sees it.
"""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = [
    (
        b"content-security-policy",
        b"default-src 'self'; frame-ancestors 'none'; form-action 'self'",
    ),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),  # NOT no-referrer: see the module docstring
    (b"cache-control", b"no-store"),
]
MAX_BODY = 8 * 1024


class Guard:
    def __init__(self, app: ASGIApp, *, port: int, token: str) -> None:
        self.app, self.token = app, token
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        headers = {k.decode("latin1"): v.decode("latin1") for k, v in scope["headers"]}

        async def send_h(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), *HEADERS]}
            await send(msg)

        deny = None
        if headers.get("host") not in self.hosts:
            deny = PlainTextResponse("Invalid host header", 400)
        elif scope["method"] not in ("GET", "HEAD"):  # POST today; PUT/DELETE too
            origin = headers.get("origin")
            same = (
                origin in self.origins
                if origin is not None
                else headers.get("sec-fetch-site") == "same-origin"
            )
            if not same:
                deny = PlainTextResponse("Forbidden origin", 403)
            else:
                body = await self._read_body(receive)
                got = parse_qs(body.decode("utf-8", "replace")).get("token", [""])[0]
                if len(body) > MAX_BODY:
                    deny = PlainTextResponse("Request body too large", 403)
                elif not hmac.compare_digest(got.encode(), self.token.encode()):
                    # The daemon may have restarted since the page loaded (new token).
                    deny = PlainTextResponse(
                        "Forbidden token: this page is out of date. "
                        "Reload it and try again.",
                        403,
                    )
                else:
                    return await self.app(scope, _replay(body, receive), send_h)
        if deny is not None:
            return await deny(scope, receive, send_h)
        return await self.app(scope, receive, send_h)

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        body = b""
        while len(body) <= MAX_BODY:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        return body


def _replay(body: bytes, receive: Receive) -> Receive:
    replayed = False

    async def receive_again() -> Message:
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": body}
        return await receive()

    return receive_again
