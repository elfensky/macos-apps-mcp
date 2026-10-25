"""Spikes 009-011 harness: a public page calls loopback mock dashboards (#483).

Three servers, all bound to 127.0.0.1:
- 47698: the page (``/``, ``/app.js``) and ``POST /report``; the only port the
  cloudflared quick tunnel exposes, so the page has a public https origin;
- 47699: a mock dashboard paired with the page's origin;
- 47697: a mock dashboard paired with another origin; the page must not read it.

The mocks copy the request layer #483 proposes for ``dashboard/guard.py``: the Host
check, CORS only for the paired origin, the key in ``Authorization: Bearer``, and the
form token on a POST. Every mock request goes to ``requests.jsonl`` and every page
report to ``results-<browser>.json``. The tunnel origin is written as ``<tunnel>``.

Usage: uv run python serve.py --origin https://<name>.trycloudflare.com --key <key>
"""

from __future__ import annotations

import argparse
import hmac
import json
import re
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HERE = Path(__file__).parent
TOKEN = "spike-form-token"
MAX_BODY = 8 * 1024
PAGE = (
    '<!doctype html><title>mock</title><main id="m"><h2>Health (mock)</h2>'
    "<p>Mail adapter: on</p>"
    '<form method="post" action="/toggle"><input type="hidden" name="token" '
    f'value="{TOKEN}"><input name="adapter" value="mail"></form></main>'
)
PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00"
    b"\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
_lock = threading.Lock()


def _browser(ua: str) -> str:
    for name in ("Edg", "Chrome", "Firefox"):
        if m := re.search(rf"{name}/(\d+)", ua):
            return f"{name.lower()}-{m.group(1)}"
    if m := re.search(r"Version/(\d+)[\d.]* .*Safari/", ua):
        return f"safari-{m.group(1)}"
    return "unknown"


def _mask(value: str | None, tunnel: str) -> str | None:
    return value.replace(tunnel, "<tunnel>") if value and tunnel else value


class Mock(BaseHTTPRequestHandler):
    """A loopback dashboard that answers CORS for one paired origin only."""

    paired = ""
    tunnel = ""
    key = ""
    port = 0

    def log_message(self, *args) -> None:
        pass

    def log_error(self, format, *args) -> None:
        # a request the parser rejects, for example a TLS hello from an https upgrade
        row = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "port": self.port,
            "error": (format % args)[:160],
        }
        with _lock, (HERE / "requests.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    def _auth(self) -> str:
        got = self.headers.get("Authorization")
        if got is None:
            return "none"
        return "ok" if hmac.compare_digest(got, f"Bearer {self.key}") else "bad"

    def _record(self, status: int) -> None:
        h = self.headers
        row = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "port": self.port,
            "method": self.command,
            "path": self.path,
            "status": status,
            "origin": _mask(h.get("Origin"), self.tunnel),
            "host": h.get("Host"),
            "browser": _browser(h.get("User-Agent", "")),
            "auth": self._auth(),
            "cookie": h.get("Cookie") is not None,
            "fetch_headers": {
                k.lower(): _mask(v, self.tunnel)
                for k, v in h.items()
                if k.lower().startswith(("sec-fetch-", "access-control-"))
                or "private-network" in k.lower()
                or "local-network" in k.lower()
            },
        }
        with _lock, (HERE / "requests.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    def _send(self, status: int, body: str | bytes = "", extra: dict | None = None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        if self.headers.get("Origin") == self.paired:
            self.send_header("Access-Control-Allow-Origin", self.paired)
            self.send_header("Vary", "Origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if isinstance(body, bytes):
            ctype = "image/gif"
        elif body.startswith("<!doctype"):
            ctype = "text/html; charset=utf-8"
        else:
            ctype = "text/plain; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        self._record(status)

    def _host_ok(self) -> bool:
        # the same two names dashboard/guard.py accepts
        host = self.headers.get("Host")
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def do_OPTIONS(self) -> None:
        if not self._host_ok() or self.headers.get("Origin") != self.paired:
            return self._send(403, "preflight refused")
        allow = {
            "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "authorization, content-type",
            "Access-Control-Max-Age": "0",  # a preflight per call, so each is logged
        }
        self._send(204, extra=allow)

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(421, "wrong Host")
        path = self.path.split("?", 1)[0]
        if path == "/pixel.gif":  # an image cannot send a header, so no key here
            return self._send(200, PIXEL)
        if path == "/hello":  # a top-level navigation, approach A in #483
            return self._send(200, "approach A: a navigation reached the mock")
        if path != "/page":
            return self._send(404, "not found")
        if self._auth() != "ok":
            return self._send(401, "needs the key")
        self._send(200, PAGE)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, "body too large")
        form = parse_qs(self.rfile.read(length).decode())
        if not self._host_ok():
            return self._send(421, "wrong Host")
        if self.headers.get("Origin") != self.paired:
            return self._send(403, "foreign Origin")
        if self._auth() != "ok":
            return self._send(401, "needs the key")
        if form.get("token") != [TOKEN]:
            return self._send(403, "bad form token")
        self._send(200, "toggled")


class Page(BaseHTTPRequestHandler):
    """Serves the page through the tunnel and takes its same-origin reports."""

    tunnel = ""
    FILES = {
        "/": ("index.html", "text/html"),
        "/app.js": ("app.js", "text/javascript"),
    }
    # The loader CSP #483 proposes: own script only, network only to the loopback ports.
    CSP = (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self' http://127.0.0.1:47632 http://127.0.0.1:47697 "
        "http://127.0.0.1:47699 http://localhost:47699; "
        "img-src http://127.0.0.1:47699 http://localhost:47699; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )

    def log_message(self, *args) -> None:
        pass

    def _reply(self, status: int, data: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", self.CSP)
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        entry = self.FILES.get(self.path.split("?", 1)[0])
        if entry is None:
            return self._reply(404, b"not found")
        name, ctype = entry
        self._reply(200, (HERE / "public" / name).read_bytes(), ctype)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if self.path != "/report" or length > 64 * 1024:
            return self._reply(404, b"not found")
        report = json.loads(self.rfile.read(length))
        browser = _browser(self.headers.get("User-Agent", ""))
        text = _mask(json.dumps(report, indent=2), self.tunnel)
        (HERE / f"results-{browser}.json").write_text(text + "\n")
        print(f"report from {browser}: {sum(s['ok'] for s in report['steps'])} ok")
        self._reply(204)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", required=True, help="the tunnel's https origin")
    ap.add_argument("--key", required=True, help="the throwaway spike key")
    args = ap.parse_args()
    origin = args.origin.rstrip("/")
    roles = {
        47698: type("PageHere", (Page,), {"tunnel": origin}),
        47699: type(
            "Paired",
            (Mock,),
            {"paired": origin, "tunnel": origin, "key": args.key, "port": 47699},
        ),
        47697: type(
            "Unpaired",
            (Mock,),
            {
                "paired": "https://not-paired.example",
                "tunnel": origin,
                "key": args.key,
                "port": 47697,
            },
        ),
    }
    servers = [ThreadingHTTPServer(("127.0.0.1", p), h) for p, h in roles.items()]
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print("ready: page 47698, paired mock 47699, unpaired mock 47697", flush=True)
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
