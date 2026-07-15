# Credits & prior art

macos-apps-mcp stands on a lot of prior work. This file credits the projects it references, learns from,
will build on, and depends on. Corrections welcome — open an issue.

## Prior art — referenced & learned from (no code reused)

- **[mcp-server-apple-events](https://github.com/FradSer/mcp-server-apple-events)** by **Frad LEE** (MIT)
  — the behavioral / feature-parity reference for our EventKit Calendar & Reminders adapters. macos-apps-mcp
  re-implements that surface independently in Python (PyObjC) and consolidates it; no code is reused.
- **[apple-mcp](https://github.com/supermemoryai/apple-mcp)** by **Dhravya Shah** (MIT, archived;
  formerly `Dhravya/apple-mcp`) — pioneered the "all Apple apps in one MCP server" pattern. macos-apps-mcp
  learned from it by *negative example*: it returned full note/email bodies inline (context bloat), so
  macos-apps-mcp returns citable pointers instead (*pointers, not payload*). No code reused.
- **[apple-mcp / per-app servers](https://github.com/griches/apple-mcp)** by **Gary Riches**
  (**no license declared**) — architectural inspiration for the modular *one-adapter-per-app* shape.
  Because no license is declared, **no code is copied** from it; the influence is pattern only.
- **[osxphotos](https://github.com/RhetTbull/osxphotos)** by **Rhet Turnbull** (MIT) — the reference
  for any future Apple Photos access. Currently **deferred and unused** (media lives in Immich; the
  Photos extra is intentionally omitted), credited for the design influence.

## Code we build on / will port

- **[apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp)** by **Patrick Freyer** (MIT)
  — the basis for macos-apps-mcp's Apple Mail adapter (**planned for v1.5**; `adapters/mail.py` is a stub
  today). When that port lands, the ported files will retain Patrick Freyer's copyright and the MIT
  notice. Our fork ([`elfensky/apple-mail-mcp`](https://github.com/elfensky/apple-mail-mcp),
  `working` branch) also carries community contributions that are still open upstream and will be
  credited in the ported files — each author holds copyright in their additions under the same MIT terms:
  - **ahharvey** — raw RFC 822 source ([#66](https://github.com/patrickfreyer/apple-mail-mcp/pull/66))
  - **Brendan DeBeasi** — email attachments ([#51](https://github.com/patrickfreyer/apple-mail-mcp/pull/51)) and reply-by-id ([#49](https://github.com/patrickfreyer/apple-mail-mcp/pull/49))
  - **elfensky** — `message_id` / `mail_link` surfacing ([#76](https://github.com/patrickfreyer/apple-mail-mcp/pull/76))

## Standards & dependencies

- **[Model Context Protocol](https://modelcontextprotocol.io)** — the open standard macos-apps-mcp
  implements (stewarded by Anthropic).
- **[FastMCP](https://github.com/PrefectHQ/fastmcp)** (2.0) by **Jeremiah Lowin** / **PrefectHQ**
  (Apache-2.0) — the server framework macos-apps-mcp is built on.
- **[PyObjC](https://github.com/ronaldoussoren/pyobjc)** by **Ronald Oussoren** and contributors
  (MIT) — the EventKit bindings the Calendar/Reminders adapters call into.

## License notes

macos-apps-mcp's only planned code port is the Apple Mail adapter (from `patrickfreyer/apple-mail-mcp`, MIT).
When v1.5 lands, the ported files must retain the upstream MIT copyright + permission notice and credit
the individual PR authors above. Everything else here is a reference, an architectural influence, or a
runtime dependency — no source is copied. **`griches/apple-mcp` has no license, so nothing may be
copied from it.** FastMCP (Apache-2.0) and PyObjC (MIT) are normal dependencies; if their source is ever
bundled, their `LICENSE`/`NOTICE` files travel with it.
