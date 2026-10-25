---
spike: 010
idea: dashboard-loader
name: loader-safari-loopback
type: standard
validates: "Given the spike 009 page in Safari 27.0.1, when it fetches the loopback mocks, loads loopback images and navigates to a loopback URL, then each is allowed or blocked as mixed content"
verdict: INVALIDATED
related: [009, 011]
tags: [dashboard, loader, safari, webkit, mixed-content, loopback]
---

# Spike 010: the loader path in Safari

## What This Validates

Given the spike 009 page on a public https origin in Safari 27.0.1 (macOS 27), when it runs
the same fetch checks, loads an image from `127.0.0.1` and `localhost`, and navigates the tab
to `http://127.0.0.1`, then Safari allows or blocks each one (#483).

**Answer:**

- **Safari blocks every scripted loopback request.** Every `fetch` fails at once (0–3 ms)
  with `TypeError: Load failed`: `cors` and `no-cors`, `127.0.0.1` and `localhost`, with and
  without the key. No request reaches the mock, so the block happens before the network.
  The loader of #483 cannot work in Safari.
- **Safari has no Local Network Access.** `navigator.permissions.query()` throws `TypeError`
  for `loopback-network` and `local-network`, and no prompt shows.
- **Loopback images load.** An `<img>` from `http://127.0.0.1` and from `http://localhost`
  arrives at the mock (`sec-fetch-dest: image`) and loads. Images carry no usable data back,
  so they do not help the loader.
- **A top-level navigation works.** A plain link from the https page to
  `http://127.0.0.1:47699/hello` reaches the mock (`sec-fetch-mode: navigate`) and shows the
  page. Safari does not upgrade it to https. Approach A of #483 (a link or redirect to the
  local dashboard) works in Safari.

## Research

- WebKit treats loopback as mixed content and does not follow the secure-contexts spec
  ([WebKit 171934](https://bugs.webkit.org/show_bug.cgi?id=171934), open).
- Safari 18 began blocking non-upgradable mixed content. A targeted fix for loopback image
  loads landed in March 2025
  ([WebKit 279249](https://bugs.webkit.org/show_bug.cgi?id=279249)). Its duplicate's title
  ("Allow access to localhost and loopback address") suggested `localhost` might pass where
  `127.0.0.1` does not, so both are probed.
- The Chrome guidance lists Local Network Access as unsupported in Safari.

## How to Run

The spike 009 harness and page. In Safari: open the link, click **Run**, then click **open
the mock in this tab**.

## Investigation Trail

1. **Run 1:** every fetch failed in 0–1 ms. Nothing reached a mock.
2. **Run 2 added `localhost` fetch and image rows.** `localhost` fetch failed the same way.
   The image requests reached the mock and got `404` from a harness bug (the `?t=` query).
3. **Run 3:** both images load (`200 img`). Every fetch still fails.
4. **Navigation:** the first click left no request in the log (most likely not clicked). On
   the second click the mock logged `GET /hello 200`, `sec-fetch-mode: navigate`, and no TLS
   hello, and Andrei saw the page text.

## Results

**INVALIDATED** for the loader: Safari 27.0.1 blocks `fetch` from an https page to
`http://127.0.0.1` and `http://localhost`, and it has no permission to ask for. Two ways
remain for Safari:

- **Approach A:** a link or redirect that navigates to `http://127.0.0.1:47632`. It works
  today, but the address bar ends on `127.0.0.1`.
- **Approach C:** the daemon serves https on loopback with a certificate for a real name
  (the `*.plex.direct` pattern). It needs a certificate service. Not probed.
