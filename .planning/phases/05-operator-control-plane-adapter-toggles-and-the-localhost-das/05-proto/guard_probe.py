"""Run: uv run python guard_probe.py  (prints one line per case; asserts the outcome)."""
import asyncio
import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from guard_proto import Guard, assert_loopback

async def ok(request):
    if request.method == "POST":
        form = (await request.body()).decode()
        return PlainTextResponse("posted " + form)
    return PlainTextResponse("ok")

app = Guard(Starlette(routes=[Route("/", ok, methods=["GET", "POST"])]), 47632, "T0K")
H = "127.0.0.1:47632"

async def main():
    t = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=t, base_url="http://x") as c:
        async def case(name, want, method="GET", **kw):
            r = await c.request(method, "/", **kw)
            print(f"{name:42} -> {r.status_code}")
            assert r.status_code == want, (name, r.status_code, r.text)
            return r
        r = await case("GET good host", 200, headers={"host": H})
        assert r.headers["content-security-policy"].startswith("default-src 'self'")
        assert r.headers["referrer-policy"] == "same-origin"
        await case("GET host evil.com", 400, headers={"host": "evil.com"})
        await case("GET host evil.com:47632", 400, headers={"host": "evil.com:47632"})
        await case("GET host 127.0.0.1 no port", 400, headers={"host": "127.0.0.1"})
        await case("GET host localhost:47632", 200, headers={"host": "localhost:47632"})
        ok_h = {"host": H, "origin": f"http://{H}", "content-type": "application/x-www-form-urlencoded"}
        r = await case("POST good", 200, "POST", headers=ok_h, content="token=T0K&adapter=photos")
        assert "adapter=photos" in r.text  # body replayed to the handler
        await case("POST wrong token", 403, "POST", headers=ok_h, content="token=nope")
        await case("POST no token", 403, "POST", headers=ok_h, content="a=b")
        await case("POST foreign origin", 403, "POST", headers={**ok_h, "origin": "http://evil.com"}, content="token=T0K")
        await case("POST Origin: null", 403, "POST", headers={**ok_h, "origin": "null"}, content="token=T0K")
        no_o = {k: v for k, v in ok_h.items() if k != "origin"}
        await case("POST no Origin, no Sec-Fetch-Site", 403, "POST", headers=no_o, content="token=T0K")
        await case("POST no Origin, Sec-Fetch-Site same-origin", 200, "POST", headers={**no_o, "sec-fetch-site": "same-origin"}, content="token=T0K")
        await case("POST no Origin, Sec-Fetch-Site cross-site", 403, "POST", headers={**no_o, "sec-fetch-site": "cross-site"}, content="token=T0K")
        await case("POST oversize body", 403, "POST", headers=ok_h, content="token=T0K&x=" + "a" * 20000)
    for bad in ("0.0.0.0", "192.168.1.5", "localhost", "::"):
        try:
            assert_loopback(bad); raise SystemExit(f"{bad} was accepted")
        except ValueError:
            print(f"assert_loopback({bad!r}) refused")
    for good in ("127.0.0.1", "::1"):
        assert assert_loopback(good) == good
    print("ALL OK")

asyncio.run(main())
