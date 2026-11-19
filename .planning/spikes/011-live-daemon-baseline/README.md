---
spike: 011
idea: dashboard-loader
name: live-daemon-baseline
type: standard
validates: "Given the live daemon at 127.0.0.1:47632, when the public page sends a no-cors GET and a CORS GET without a key, then the requests arrive but the page reads nothing"
verdict: VALIDATED
related: [009, 010]
tags: [dashboard, guard, cors, baseline, loopback]
---

# Spike 011: the live daemon against a public page today

## What This Validates

Given the live daemon on `127.0.0.1:47632`, when the spike 009 page sends a
`no-cors` GET of `/` and a CORS GET of `/health` without a key, then the requests arrive but
the page reads nothing. Today's Guard already refuses a public site, and the loader of #483
adds the only way in.

**Answer:**

- **Chrome 156 and Zen (Firefox 158): the `no-cors` GET reaches the daemon** after the
  loopback prompt, and the page gets an opaque response with no status and no body. **The
  CORS GET fails with `TypeError`**: the daemon sends no `Access-Control-Allow-Origin`, so the
  browser hides the answer.
- **Safari 27: both fail before the network** (spike 010).
- **No POST was sent to the live daemon.** The dashboard's write path stays untested by
  design. The mock in spike 009 carries the POST checks.

## How to Run

The spike 009 harness and page. Rows `011-live-nocors` and `011-live-cors`.

## Results

**VALIDATED.** A public page can reach the daemon's port only after the loopback permission
(Chrome, Firefox), and even then it reads nothing: no CORS answer, no cookie, `403` without
the key (`curl` shows `403` on `/` without a key). The loader of #483 opens exactly one
origin: the paired one.
