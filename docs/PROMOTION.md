# Promotion and listings

Where macos-apps-mcp is listed, how each listing stays current, the launch plan, and the rules for
every post. Status as of 2026-10-26 (v0.15.1). Release mechanics are in [RELEASING.md](RELEASING.md).
A session that picks up promotion work starts at [Next steps](#next-steps--start-here).

## Next steps — start here

State on 2026-10-26: the server is live on PyPI, the official MCP Registry, GitHub releases, Glama
(scored, A) and as a Claude Code plugin. The X account exists. The lav.ren entries are merged as drafts.
Weeks 1–2 of the [launch plan](#launch-plan) are done.

| # | Step | Who | Done when |
|---|---|---|---|
| 1 | Send [the tester brief](tester-brief.md) to 3–5 Mac users; collect answers in Discussions; fix every setup blocker they hit | Owner sends; a session fixes | ≥ 3 testers finish a first task without help |
| 2 | Set up [@macosappsmcp](https://x.com/macosappsmcp): avatar `sips -Z 400 docs/images/logo.png --out avatar.png`, banner `docs/images/x-banner.png`, bio from [X](#x); first post = the release post there | Owner | Profile complete, one post |
| 3 | Glama: on the [admin pages](https://glama.ai/mcp/servers/elfensky/macos-apps-mcp/admin/profile), check the short description and set it to the text below if it differs; if [the awesome-mcp-servers PR](https://github.com/punkpeye/awesome-mcp-servers/pull/17609) is still open on 2026-10-29, comment once that the Glama score is live | Owner | Description current; PR merged |
| 4 | Raise Glama's grade (3.7 overall, coherence 2.8 C): Phase 05.10, [#514](https://github.com/elfensky/macos-apps-mcp/issues/514) — parameter descriptions, `verb_noun` names in one breaking release, merged duplicates, Contacts update and delete, `MACOS_APPS_ALLOW_SEND=mail` in Glama's build spec; breakdown on the [score page](https://glama.ai/mcp/servers/elfensky/macos-apps-mcp/score) | Session | Overall ≥ 4.3 and coherence ≥ 3.5 after the next Glama build |
| 5 | Submit to the [Cline MCP Marketplace](https://github.com/cline/mcp-marketplace) (an issue with the repo URL, a reason and a 400×400 logo: `sips -Z 400 docs/images/logo.png --out logo-400.png`) and [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) (its issue form); fill in [mcpservers.org](https://mcpservers.org/submit) | Session drafts, owner approves | Three submissions open |
| 6 | Demo kit: a seed script for a separate macOS test user (calendar, reminders, notes, an iCloud or IMAP test mailbox) and a 60 s shot list | Session, then owner records | Video on fake data |
| 7 | Week 4: publish the project page in the [lav.ren repo](https://github.com/elfensky/lav.ren) (private; local checkout `~/Developer/lav.ren`; `src/content/projects/macos-apps-mcp/index.mdx`, `draft: false`, following that repo's AGENTS.md); add its blog link when the blog section opens | Session in lav.ren | Page live |
| 8 | Week 5: Show HN, Reddit, X launch post | Owner | Objections answered the same day |
| 9 | Week 6: `.mcpb`, Smithery, Anthropic plugin directory | Session | Listed |
| 10 | The next release (0.15.2, not yet scheduled) ships the Linux install to PyPI; afterwards clear Glama's pinned commit so Auto-Release builds each release | Release session | Glama builds the release commit unpinned |

Glama short description (step 3):

> One local MCP server for Mail, Calendar, Reminders, Notes, Messages and five more macOS apps.
> Searches return pointers, not full bodies; deletes, moves and sends preview first; sending is off by
> default.

Waiting on others: PulseMCP and mcp.directory copy from the official registry by themselves.

## Listings

| Listing | Where | How it updates | Status |
|---|---|---|---|
| GitHub | [elfensky/macos-apps-mcp](https://github.com/elfensky/macos-apps-mcp) | README on `develop` (also the PyPI description at release) | Live; 12 topics, Discussions on |
| PyPI | [macos-apps-mcp](https://pypi.org/project/macos-apps-mcp/) | `publish.yml`, `target=pypi`, dispatched on the release tag | Live, 0.15.1 |
| Official MCP Registry | [`io.github.elfensky/macos-apps-mcp`](https://registry.modelcontextprotocol.io/?q=io.github.elfensky/macos-apps-mcp) ([API](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.elfensky/macos-apps-mcp)) | `publish.yml` publishes `server.json` right after the PyPI upload | Live, 0.15.1, active, with the logo |
| GitHub releases | [Releases](https://github.com/elfensky/macos-apps-mcp/releases) | `gh release create`, then the notarized `.app` zip | Live, 0.15.1 |
| Claude Code plugin | This repo (`.claude-plugin/marketplace.json`, `plugin/`) | Follows `develop`; the server is `uvx macos-apps-mcp`, unpinned | Live: `/plugin marketplace add elfensky/macos-apps-mcp`, then `/plugin install macos-apps@macos-apps-mcp` |
| Glama | [elfensky/macos-apps-mcp](https://glama.ai/mcp/servers/elfensky/macos-apps-mcp) | Profile edited on Glama; `glama.json` names the maintainer | Claimed; scored 2026-10-26, badge in the README: see [Glama score](#glama-score) |
| X | [@macosappsmcp](https://x.com/macosappsmcp) | Posts by hand; see [X](#x) | Created 2026-10-25; reposts releases |
| mcprepository.com | [elfensky/macos-apps-mcp](https://mcprepository.com/elfensky/macos-apps-mcp) | Crawls GitHub by itself | Live |
| awesome-mcp-servers | [PR #17609](https://github.com/punkpeye/awesome-mcp-servers/pull/17609), OS Automation | One line with the Glama badge | Open; the Glama score its bot asks for exists since 2026-10-26 |
| lav.ren | `src/content/projects/macos-apps-mcp/` and `src/content/blog/2026-10-apple-mail-says-ok.mdx` in the site repo | `draft: true` → `false` publishes | Drafts. The project page goes live first; the blog link is added when the blog section opens |
| PulseMCP, mcp.directory | — | Both copy from the official registry | Not yet picked up (PulseMCP pauses submissions) |

### Not listed yet

| Listing | How | When |
|---|---|---|
| Anthropic plugin directory | Submit the plugin at claude.ai/directory/manage (Pro or Max account). The first organization to submit a repo folder owns the listing. Local servers in plugins run in Claude Code and local Cowork, not in claude.ai chat. | After the testers (week 6) |
| `.mcpb` bundle | `server.type: "uv"`; Claude Desktop chat installs it with one click. Test on a clean Mac and on Intel first. | Week 6 |
| Smithery | Needs the `.mcpb` (its only path for a local server) | After the `.mcpb` |
| Cline MCP Marketplace | A GitHub issue on `cline/mcp-marketplace` with the repo URL, a 400×400 PNG logo and a reason | Any time |
| mcpservers.org | Free submit form (skip the paid option) | Any time |
| awesome-claude-code | Its issue form (the repo is older than 14 days and active) | Any time |
| Skip | mcp.so (paid only), LobeHub (OAuth to every repo), Docker MCP catalog (cannot reach Mac apps) | — |

## Rules for every listing and post

- **Mechanisms, never guarantees.** "Deletes, moves and sends preview first; every write is logged."
  Never "it cannot lose your mail". Creates and edits act when called.
- **The dashboard needs the signed `.app` daemon.** A `uvx` install has no dashboard.
- **The server is local, the conversation is not.** What Claude reads through the server goes to Claude
  like any other chat content.
- **Invented data only** in screenshots and demos. `scripts/dashboard_demo.py` serves the real dashboard
  on made-up writes and keeps every state file in its own folder. Keep its Health and Backups pages out of
  screenshots: they show this Mac's paths and pids.
- **Review before it goes out.** Every listing text, post and change gets a multi-model review (Claude
  Octopus `orchestrate.sh spawn`, run from an empty folder with the diff pasted in). Each finding is checked
  against the code before it is taken: reviewers have cited stale branches as fact. A claim the code does
  not back is cut.
- **No telemetry, ever.** Measure with GitHub Insights → Traffic (referrers such as `t.co`,
  `news.ycombinator.com`), stars, Discussions, issues with `doctor` output, the PyPI download trend, and
  the Usage tab of the Anthropic directory once listed.

## Launch plan

| Week | Work | Done when |
|---|---|---|
| 1 | README first screen, CREDITS provenance, topics, Discussions | Done (#472) |
| 2 | Registry metadata, Glama claim and score, awesome-list PR, plugin marketplace | Done (#474, #480, #487, release 0.15.1); awesome PR open |
| 3 | 3–5 testers with [the tester brief](tester-brief.md); fix every setup blocker; record a 60 s demo on fake data | ≥ 3 testers finish a first task without help |
| 4 | Publish the lav.ren project page; the Mail post when the blog opens; an X thread | Strangers ask questions or open issues |
| 5 | Show HN (link the repo, not a post), r/ClaudeAI, r/mcp, r/macapps (check each sidebar), X launch post | Actionable objections answered the same day |
| 6 | `.mcpb`, Smithery, Anthropic plugin directory | Listed, Desktop install under 2 minutes |
| After | One post per release with one visible change | — |

## X

Post from the maintainer's personal account until the server has users; a maker's voice reaches further
than a new project account. The project account [@macosappsmcp](https://x.com/macosappsmcp) (created
2026-10-25) reposts those posts and carries the release notes.

| When | What | Time |
|---|---|---|
| Weeks 3–4 | 1–2 posts per week: one dashboard screenshot, one Mail trap per post | 15 min each |
| Weeks 3–4 | Search X for "apple mail mcp", "calendar mcp", "claude code mac"; answer real questions, one link, no template replies | 10 min, twice a week |
| Week 4 | Thread: the Mail traps from the post, linking the project page | 1 h |
| Week 5 | Launch post with a native 30–60 s demo video; links in the first reply; stay for replies | 2 h |

That X ranks posts with links lower is widely reported but not confirmed; links in the first reply avoid
the question.

Profile kit for the project account: avatar = `docs/images/logo.png` at 400×400; banner =
`docs/images/x-banner.png` (1500×500, the logo plus the dark dashboard on invented data); bio "Local MCP server for Mail, Calendar, Reminders, Notes and more on
macOS. Open source."; link = the repo.

Draft posts (under 280 characters each):

```text
I let an AI agent move my mail. This is what it leaves behind: every message backed up
before it moved, and a prompt that brings the batch back (Claude previews the undo first).
Local MCP server for Mail, Calendar, Notes and more on macOS. Open source.
[image: docs/images/dashboard-batch.png] (repo link in reply)
```

```text
Apple Mail trap: `delete` after `send` returns fine, deletes nothing, and the mail goes out
anyway. So once a send starts, the only honest answer is "here's what's still in the Outbox".
One of the Mail traps I hit building a Mail server for AI agents.
```

```text
macos-apps-mcp: one local MCP server for Mail, Calendar, Reminders, Notes, Messages and five
more Mac apps. Searches return ids, not bodies. Deletes, moves and sends preview first.
Every write it makes is logged.
[60 s demo video] (links in reply)
```

Release post for the project account (0.15.1):

```text
v0.15.1 is out.
· Listed in the official MCP Registry: io.github.elfensky/macos-apps-mcp
· A Claude Code plugin: two commands, in the README
· Dashboard fixes, security updates
Local MCP server for Mail, Calendar, Notes and more on macOS.
(links in reply)
```

The demo video needs fake data in the real apps: record it in a separate macOS user account with a test
calendar and a test mail account (iCloud or IMAP; Gmail label moves are refused).

## Glama score

The awesome-mcp-servers bot asks for a Glama quality score. Glama scores a server only after a **Glama
release**, which is not a GitHub release:

1. On the listing's Dockerfile admin page, set the build spec and click **Build**. Glama builds the server
   in a Linux container, starts it and reads `tools/list`.
2. When the build test succeeds, click **Make Release**. Glama then runs its security checks and grades
   the tool definitions and how the tools fit together.
3. Auto-Release (on) rebuilds on every GitHub release after that.

Build spec on the Dockerfile admin page (base image `debian:trixie-slim`, Python 3.12, Node 24 — Glama's
defaults):

| Field | Value |
|---|---|
| Build steps | `["uv sync --locked --no-dev"]` |
| CMD arguments | `["mcp-proxy", "--", "uv", "run", "--no-sync", "macos-apps-mcp"]` |
| Env var JSON schema | empty |
| Pinned commit | `bedeb025d07bb04a8eb7f42656f12f8cc0eb1d44` (a `develop` commit that has the Linux start) |

With no pinned commit, Glama builds the commit it last indexed, which can predate a fix: an unpinned build
on 2026-10-26 checked out an older commit and failed on PyObjC. Glama's own advice for an OS-specific
server (Discord, 2026-10-26) matches what the server does: environment markers on the macOS-only
dependencies, and a clear "macOS only" error from every tool that needs a Mac.

Off macOS the server starts and lists its tools, and every tool that needs a Mac refuses with a "macOS
only" error (`ping`, `now` and `usage` still answer);
the `linux-tools-list` CI job keeps that build test green. Glama scored the server on 2026-10-26: overall
3.7 (A), tool definition quality 4.1 (A), coherence 2.8 (C), over the 68 tools listed without
`MACOS_APPS_ALLOW_SEND`. The breakdown is on the [score page](https://glama.ai/mcp/servers/elfensky/macos-apps-mcp/score).

## Screenshots

`docs/images/dashboard-*.png` come from the real dashboard on invented data:

```sh
uv run python scripts/dashboard_demo.py "$(mktemp -d)"
```

Open the printed `/key?k=…` link in a fresh browser profile, capture at 1280×640 at 2×, light and dark,
and scale to 1600 px wide (`sips -Z 1600`). The logo is `packaging/AppIcon.icon` exported at 512 px with
Icon Composer's `ictool` and re-encoded as an 8-bit PNG.
