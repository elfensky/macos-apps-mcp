# Credits & prior art

macos-apps-mcp stands on a lot of prior work. This file credits the projects it references, learns from,
and depends on. Corrections welcome — open an issue.

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
- **[apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp)** by **Patrick Freyer** (MIT)
  — the reference for the Apple Mail adapter. macos-apps-mcp learned three things from it: the
  `message://` deeplink encoding (the Message-ID percent-encoded between uppercase `%3C` and `%3E`),
  the needs-response and awaiting-reply triage ideas, and mailbox creation as a tool. Its issue #58
  (an orphaned server and a hung Apple Event that pinned Mail) shaped the orphan watcher and the
  child cleanup. The code is independent: the adapter reads Mail's Envelope Index and classifies in
  pure Python, where apple-mail-mcp builds one AppleScript per account. No code reused. Our fork
  ([`elfensky/apple-mail-mcp`](https://github.com/elfensky/apple-mail-mcp), `working` branch) also
  carries community contributions that are still open upstream. They are credited here for the ideas
  their pull requests carried:
  - **ahharvey** — raw RFC 822 source ([#66](https://github.com/patrickfreyer/apple-mail-mcp/pull/66))
  - **Brendan DeBeasi** — email attachments ([#51](https://github.com/patrickfreyer/apple-mail-mcp/pull/51)) and reply-by-id ([#49](https://github.com/patrickfreyer/apple-mail-mcp/pull/49))
  - **elfensky** — `message_id` / `mail_link` surfacing ([#76](https://github.com/patrickfreyer/apple-mail-mcp/pull/76))

## Code we build on

- **[osxphotos](https://github.com/RhetTbull/osxphotos)** by **Rhet Turnbull** (MIT) — a runtime
  dependency since Phase 4: Photos search, albums, per-photo metadata and export read the library
  through it.

## Standards & dependencies

- **[Model Context Protocol](https://modelcontextprotocol.io)** — the open standard macos-apps-mcp
  implements (stewarded by Anthropic).
- **[FastMCP](https://github.com/PrefectHQ/fastmcp)** (2.0) by **Jeremiah Lowin** / **PrefectHQ**
  (Apache-2.0) — the server framework macos-apps-mcp is built on.
- **[PyObjC](https://github.com/ronaldoussoren/pyobjc)** by **Ronald Oussoren** and contributors
  (MIT) — the EventKit bindings the Calendar/Reminders adapters call into.
- **[bpylist2](https://github.com/parabolala/bpylist2)** 4.1.1 by **Jenia Varavva** (MIT, declared
  only in the package metadata; upstream ships no licence text) — bundled in the `.app` as an
  osxphotos dependency.

## License notes

No source is copied from any project listed here: each one is a reference, an architectural influence, or a
runtime dependency. **`griches/apple-mcp` has no license, so nothing may be
copied from it.** FastMCP (Apache-2.0) and PyObjC (MIT) are normal dependencies; if their source is ever
bundled, their `LICENSE`/`NOTICE` files travel with it.
