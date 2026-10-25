---
spike: 009
idea: dashboard-loader
name: loader-chrome-lna
type: standard
validates: "Given a public https page in Chrome 156, when it fetches a loopback mock dashboard with a Bearer header and POSTs a form, then Chrome asks once, the mock sees Origin = the page origin and Host = 127.0.0.1:<port>, the page reads the answers, and a mock paired with another origin stays unreadable"
verdict: VALIDATED
related: [010, 011]
tags: [dashboard, loader, chrome, firefox, local-network-access, cors, loopback]
---

# Spike 009: the loader path in Chrome (and Zen / Firefox 158)

## What This Validates

Given a page on a public https origin (a cloudflared quick tunnel) in Chrome 156, when it
fetches a loopback mock dashboard with `Authorization: Bearer <key>` and POSTs a form with
the key and the form token, then Chrome asks once for loopback access, the mock sees the
page's `Origin` and a loopback `Host`, the page reads every answer, and a second mock paired
with another origin stays unreadable (#483).

**Answer:**

- **The loader path works in Chrome 156: 10 of 10 checks pass.** A GET with the key returns
  `200` and the page shows the mock's `<main>`. A GET without the key returns a readable
  `401`. A POST with the key and the form token returns `200`. Both `127.0.0.1` and
  `localhost` work.
- **Zen (Firefox 158) behaves the same.** It shows a `loopback-network` prompt, and after
  Allow every fetch check passes. Firefox now has Local Network Access too.
- **The prompt is for `loopback-network` only.** `local-network` stays `prompt` through every
  run, so the loader never asks for the LAN. "Allow while visiting the site" persists: the
  next run starts at `granted` and its first call takes 33 ms.
- **CORS is plain CORS.** The `Authorization` header forces an `OPTIONS` preflight with
  `access-control-request-headers: authorization`. No `Access-Control-Request-Private-Network`
  or other Local Network Access header reaches the server. The mock answers with
  `Access-Control-Allow-Origin` for the paired origin only.
- **An unpaired origin reads nothing.** The other mock refuses the preflight (`403`), the
  browser never sends the GET, and the page gets `TypeError`.
- **What the server sees:** `Origin` = the page origin, `Host` = `127.0.0.1:<port>` or
  `localhost:<port>`, `Sec-Fetch-Site: cross-site`, `Sec-Fetch-Mode: cors`, no cookie.
- **The loader CSP holds.** `default-src 'none'; script-src 'self'; connect-src 'self'` plus
  the loopback ports. Nothing else loads.
- **`targetAddressSpace: "loopback"` changes nothing** for a `127.0.0.1` literal: the same
  `200`. It is optional for the loader.

## Research

- Chrome guidance: two permissions, `local-network` (RFC 1918, link-local, `.local`) and
  `loopback-network` (`127.0.0.0/8`, `::1`, `localhost`). Request from a user gesture.
  Query state with `navigator.permissions.query()`, and never query the legacy
  `local-network-access` name, which crashes older renderers. Do not rely on the deprecated
  PNA preflight headers. Not supported in Safari.
  ([guide](https://github.com/GoogleChrome/modern-web-guidance/blob/main/skills/modern-web-guidance/guides/security/local-network-access.md),
  [blog](https://developer.chrome.com/blog/local-network-access))

| Approach | Tool | Pros | Cons | Status |
|---|---|---|---|---|
| Quick tunnel + stdlib mocks | `cloudflared tunnel --url`, `http.server` | No account, no dependency, a real public origin | Cloudflare's hostname | **Chosen** |
| `--ip-address-space-overrides` | Chrome flag | No tunnel | A test-only flag, not what users run | Rejected |
| Page on own infrastructure | openresty | The real setup | A vhost first | For the build |

## How to Run

```sh
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:47698   # prints the https URL
cd .planning/spikes/009-loader-chrome-lna
uv run python serve.py --origin https://<name>.trycloudflare.com --key <throwaway key>
# open https://<name>.trycloudflare.com/#key=<throwaway key> in each browser, click Run
```

`serve.py` runs three loopback servers: the page and `POST /report` on 47698 (the only
tunnelled port), a mock paired with the page's origin on 47699, and a mock paired with
`https://not-paired.example` on 47697. The mocks copy the request layer #483 proposes for
`dashboard/guard.py`.

## What to Expect

One prompt in Chrome and Firefox on the first loopback call. Then every row is green except
`011-live-nocors` in Safari and the Safari fetch rows (spike 010).

## Observability

- `requests.jsonl`: every mock request with method, path, status, masked `Origin`, `Host`,
  key state (`ok`/`bad`/`none`), cookie presence and every `sec-fetch-*` and
  `access-control-*` header. A request the parser rejects (a TLS hello) is logged as an
  `error` row.
- `results-<browser>.json`: each page report with the permission state before and after,
  and per step the status, response type, error name and duration. The tunnel origin is
  written as `<tunnel>`.

## Investigation Trail

1. **Run 1 (Zen, Safari).** Andrei reported "Chrome asked and succeeded". The report's user
   agent said `Firefox/158` with Firefox's error text: the browser was Zen. Zen passed 7 of
   7. Safari failed every fetch in 0–1 ms.
2. **Run 2 (Chrome, Safari, Zen) added `localhost` and image rows.** Chrome reported
   `key_present: false`: the spike kept the key in `sessionStorage`, which a new tab does not
   share. Even so, the preflight passed (`204`) and the `401` answer was readable. The image
   rows failed on a harness bug: `?t=` cache-busting did not match the mock's exact path.
   Safari's image requests reached the mock anyway (spike 010).
3. **Run 3 fixed both.** The key moved to `localStorage`, and the mock strips the query.
   Chrome passed 10 of 10. Its permission read `prompt` again at the start, and Andrei's
   choice in run 2 is not recorded.
4. **Run 4 (Chrome).** Started at `granted` after "Allow while visiting the site", first call
   33 ms, 10 of 10.

## Results

**VALIDATED.** The loader path of #483 works in Chrome 156 and in Firefox 158 (Zen), with one
`loopback-network` prompt per site that persists after "Allow while visiting the site". The
daemon needs plain CORS for one paired origin and the key in `Authorization`. No Local
Network Access header is involved.

Signals for the build:

- **Keep the key in `localStorage`.** A fragment-only key is lost in any new tab that opens
  the bare URL (run 2). A loader with no key shows the `macos-apps-mcp dashboard` command,
  like the dashboard does today.
- **Ask from a user gesture.** The first loopback call waits for the prompt (1.1–3.8 s).
- **Not tested:** the Block answer. The loader needs a message for `denied`, because Chrome
  does not ask again.
