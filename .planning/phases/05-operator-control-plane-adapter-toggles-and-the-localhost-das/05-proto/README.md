# 05-proto — throwaway probes for Phase 5 research

Under `.planning/`, so ruff and pytest ignore it. Run each with `uv run python <file>` from the repo root.
Every probe binds only ephemeral ports or a temp UDS and closes at exit.

| File | Proves |
|------|--------|
| `dispatch_server.py` + `dispatch_client.py <idle\|inflight\|inflight-async>` | D-06: one uvicorn `Server`, `run(sockets=[uds, tcp])`, ASGI dispatcher; `/mcp` over TCP is 404; one lifespan startup. D-16: `should_exit`+`force_exit` exits in 0.66 s when idle or with an in-flight ASYNC call, but NEVER exits with an in-flight SYNC tool (thread) — the 3 s `os._exit(0)` watchdog in `_do_restart` fixes it (exit after 3.07 s). `PROBE_WATCHDOG=<s>` overrides the delay. |
| `origin_probe.py <policy>` | Headless Chrome 155: a same-origin form POST sends `Origin: null` under `Referrer-Policy: no-referrer`, and the real origin under `same-origin`. |
| `guard_proto.py` + `guard_probe.py` | Seed for the Host / Origin / token / headers layer and the loopback guard, tested through `httpx.ASGITransport` (14 cases + 4 refusals). |

`guard_proto.py` is a seed to port into `macos_apps_mcp/dashboard.py`, not an import target.
