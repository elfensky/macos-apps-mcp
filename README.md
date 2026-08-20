# macos-apps-mcp

One consolidated [MCP](https://modelcontextprotocol.io) server for native macOS apps —
**Calendar & Reminders** read/write, **Messages & Notes** content search over the native
stores, id-first **Mail** with draft-and-open replies, plus read-only context and a few
actions across Contacts, Photos, Safari, and Shortcuts. Python +
[FastMCP](https://github.com/PrefectHQ/fastmcp), managed with
[uv](https://docs.astral.sh/uv/).

Replaces the pile of Apple MCP servers a life-cockpit otherwise juggles with a single modular
adapter layer you own. Every read returns **pointers** (id + one-line summary + open-in-app
deeplink), never full bodies — so it structurally avoids the context-bloat bug of the archived
flagship server; bodies are a separate, bounded, opt-in fetch.

macOS only. See [DESIGN.md](DESIGN.md) for the rationale and [CHANGELOG.md](CHANGELOG.md) for
what's landed.

## Install

Requires macOS and Python ≥ 3.11.

**From source (works today):**

```sh
git clone https://github.com/elfensky/macos-apps-mcp && cd macos-apps-mcp
uv sync
```

Then point your MCP client at the project's own venv python — deterministic, and it carries the
locked PyObjC wheels:

```json
{
  "mcpServers": {
    "macos-apps": {
      "command": "/absolute/path/to/macos-apps-mcp/.venv/bin/python",
      "args": ["-m", "macos_apps_mcp"]
    }
  }
}
```

**From PyPI** (once published — see the CHANGELOG): `uvx macos-apps-mcp` runs the server with no clone,
and the MCP config becomes `"command": "uvx", "args": ["macos-apps-mcp"]` (same `"macos-apps"` key).

### Permissions (macOS TCC)

Grant access when macOS prompts — the first call to each app triggers its dialog:

- **EventKit** — Calendar + Reminders (read/write).
- **Automation** (per app) — Mail, Notes, Contacts, Photos, Safari, Messages actions/reads.
- **Full Disk Access** — required for **Messages content** (`chat.db`) and the **fast Notes**
  path (`NoteStore.sqlite`). Notes degrades to Automation without it; Messages content raises a
  clear, typed error telling you to grant it. Run the `doctor` tool to see what's granted.

## Tools

Reads return pointers; results are capped per adapter. Bodies/content are a separate bounded
fetch. Writes/actions are skipped entirely when `MACOS_APPS_READ_ONLY` is set (see below).

### Calendar & Reminders — read/write (EventKit)

| Tool | Args | Notes |
|------|------|-------|
| `events` | `when` = `today` \| `week` \| `YYYY-MM-DD` | list events as pointers |
| `free_busy` | `start`, `end` (ISO), optional `calendars` ids | merged busy intervals + free gaps in the window; no event details |
| `reminders` | `due` = `today` \| `overdue` \| `this-week` \| a list name | list reminders as pointers |
| `calendars` / `reminder_lists` | — | containers (id + name) to target writes |
| `create_event` / `update_event` | title, start, end (ISO), calendar, location, notes, `all_day`, `recurrence` | `update` is a full replace by id |
| `delete_event` | id, `span`, `dry_run` | `dry_run` previews without deleting |
| `create_reminder` / `update_reminder` | title, due, list_name, notes, `priority` (0–9), start, `recurrence` | `update` is a full replace by id |
| `complete_reminder` | id | marks complete |

A write targets its container by **name or `Pointer.id`**; an ambiguous name raises rather than
guessing. **Recurrence** is an RFC 5545 `RRULE` (`FREQ`/`INTERVAL`/`COUNT`/`UNTIL` subset, e.g.
`FREQ=WEEKLY;INTERVAL=2;COUNT=10`); a recurring reminder needs a due date; unsupported parts
(`BYDAY`, …) are rejected, not ignored.

### Mail — id-first read + draft-and-open (Automation)

Sending is **off by default**: reads, `create_draft`, and `mail_reply` never send — they
open a compose window for you to review. Outbound (`send_mail`, `reply_all`,
`forward_mail`) exists but only runs when the operator opts in via
`MACOS_APPS_ALLOW_SEND`, and `dry_run` still defaults to `True` even then.

| Tool | Args | Notes |
|------|------|-------|
| `mail` | subject-OR-sender substring | inbox matches; id = stable RFC822 message-id, `message://` deeplink |
| `mail_body` | id, mailbox | one message's plaintext, bounded + truncation-marked; `mailbox` is the `folder` value from a `mail_search` result passed back **verbatim** (or a canonical name) — **any** mailbox, not just the inbox |
| `mail_search` | subject, from_, to, mailbox, account, since, until, unread, flagged, has_attachments, body, limit | indexed search via Envelope Index (at rest — no Mail launch **unless** `account=` is a display name, which is resolved through Mail; a UUID stays pure sqlite, an unknown name raises); one result per message (INBOX **preferred**); `has_attachments` excludes inline images; `body` best-effort (indexed only) |
| `mail_index_bodies` | rebuild | builds/refreshes opt-in **FTS body index** from `.emlx` at rest; resumable, size-capped; skips not-yet-downloaded (partial coverage by design) |
| `mail_thread` | id, limit (default 100) | whole conversation, oldest-first, **includes your sent messages**; deduped; over `limit` **oldest dropped** (thread read for reply) |
| `mail_overview` | — | every mailbox with total + unread, unread-first; includes Junk/Trash/All Mail; counts live (stored counters go stale) and per distinct message; account **names** come from Mail (launches it), UUIDs stand in when it's unreachable; On My Mac always named |
| `mail_attachments` | mailbox (a search result's `folder`, verbatim — or `inbox`/`sent`/`drafts`/`trash`/`junk`), optional query | attachment name/size/downloaded per message; works on **Drafts** |
| `mail_needs_response` | — | inbox mail likely needing your reply, ranked with a `reason` (flagged / unread-direct / unanswered-direct); headers only, no bodies read |
| `mail_awaiting_reply` | `days` (1–365, default 3) | mail **you** sent ≥ `days` ago with no reply (real In-Reply-To/References threading), oldest first, reason `awaiting-reply` |
| `create_draft` | to, subject, body | opens a draft for review — **never sends**; returns a locator |
| `mail_reply` | message_id, mailbox, reply_body, `include_quote` | native threaded reply (sets In-Reply-To/References), quoted original, opens for review — **never sends** |
| `drafts` | — | list Mail drafts as pointers (id + subject — to recipient) |
| `delete_draft` | id, `dry_run` | delete one draft by message-id; `dry_run` previews |
| `create_mailbox` | name (`/` nests), account | creates the folder; missing parents auto-created. **No delete counterpart** — `delete <mailbox>` is not scriptable, so removing one is a Mail.app action |
| `move_mail` | ids (≤25), from_mailbox, to_mailbox, `dry_run` | file/archive/refile; every message backed up + logged **before** anything moves, so `mail_undo` puts it back. `dry_run` defaults to `True`. Cross-account moves leave exactly one copy |
| `trash_mail` | ids (≤25), mailbox, `dry_run` | **soft delete, and the only delete there is** — Mail's `delete` moves to the account's Trash and nothing in its scripting dictionary erases from there. Undoable via `mail_undo`; emptying Trash is yours to do in Mail.app. `dry_run` defaults to `True` |
| `mail_undo` | receipt, `dry_run` | replay a `move_mail`/`trash_mail` receipt in reverse; the undo is itself backed up and undoable |
| `update_mail_status` | ids (≤25), mailbox, `read`, `flagged`, `flag_color` | mark read/unread, flag (+colour). Re-issuing with the opposite value **is** the undo, so `dry_run` defaults to `False` |
| `mail_duplicates` | `limit` | **report only** — per-mailbox redundant-copy counts + worst offenders. Cleanup is the `dedupe-mail` CLI below; this tool cannot delete |
| `send_mail` | `to`, `subject`, `body`, `cc`, `bcc`, `html`, `from_address`, `dry_run` | **gated** by `MACOS_APPS_ALLOW_SEND`; `dry_run` defaults to `True` |
| `reply_all` | `message_id`, `mailbox`, `body`, `include_quote`, `dry_run` | **gated**; native threading headers |
| `forward_mail` | `message_id`, `mailbox`, `to`, `dry_run` | **gated**; original + attachments forwarded intact — no covering-note param (writing the body destroys both, device-verified) |

### Messages — content via chat.db (read-only; Full Disk Access)

| Tool | Args | Notes |
|------|------|-------|
| `messages_chats` | — | conversation list (id + name); no content, no FDA needed |
| `messages_search` | query, `limit` | search message **text** (decodes `attributedBody`), newest first |
| `messages_with` | contact (phone/email), `country`, `limit` | recent messages with one person; `country` = calling code or 2-letter region (locale default, never +1) |
| `message_body` | id | full text of one message by guid |

### Notes — NoteStore.sqlite reads + opt-in bodies

| Tool | Args | Notes |
|------|------|-------|
| `notes` | title/snippet substring | matching notes (id + snippet); diacritic- & smart-punctuation-insensitive |
| `notes_all` | — | every live note (id + "Account / Folder" + snippet), Recently Deleted excluded |
| `note_bodies` | ids (≤ 50) | opt-in plaintext hydration → `[{id, body}]` |
| `create_note` | title, body, optional `folder` name | returns the **stable x-coredata id**; an unknown/ambiguous folder is refused, not guessed |
| `update_note` | id, title, body | full replace of title+body by id; the stable id is preserved and verified after write |
| `delete_note` | id, `expect_title`, `dry_run` | moves to Recently Deleted; `dry_run` previews |

### Other read-only context

| Tool | Args | Returns |
|------|------|---------|
| `contacts` | name substring | cards (name, org, first phone + email) |
| `photos` | search string | media (filename); matches the Photos search field |
| `safari_tabs` | — | every open tab (url + title) |
| `shortcuts` | name substring (empty = all) | the user's Shortcuts; id = stable UUID, `shortcuts://` deeplink |
| `ping` / `now` / `doctor` | — (`doctor` takes optional `request=True` to trigger permission prompts) | health check / time / permission diagnostics |
| `audit` | optional `since` (ISO datetime) | recent write audit entries (newest first) — what macos-apps-mcp changed, with before/after pointers (enough to undo by hand) |
| `usage` | — | per-tool call counts + the never-used list, for pruning rarely-used tools |

### Actions (writes)

| Tool | Args | Notes |
|------|------|-------|
| `create_contact` | given_name, family_name, organization | |
| `run_shortcut` | name **or** id, optional `input_text` | runs a Shortcut; returns a bounded output snippet |
| `safari_open` | url | opens in a new tab; bare host → `https://`; only `http`/`https` allowed |

### Read-only mode

Set `MACOS_APPS_READ_ONLY=1` (or `true` / `yes`) to register reads only — every write and action
tool is skipped, a safe-deploy guard. (Reads may still open apps / read local stores.)

### Cleaning up duplicate mail

Mail accumulates redundant copies of the same message — a UI drag copies rather than moves, Gmail
shows one message under both a label and All Mail, migrations leave copies on two accounts. The
read tools already collapse them, so this is only about what is physically on the server. Ask a
session for `mail_duplicates()` to see the damage, then clean up in a terminal:

```sh
macos-apps-mcp dedupe-mail                       # preview every mailbox — changes nothing
macos-apps-mcp dedupe-mail --verbose             # also list the sets it will NOT touch
macos-apps-mcp dedupe-mail --execute --mailbox=<folder-url>   # do one mailbox for real
```

A **CLI command, not a tool**, for the same reason as `allow-send`: thousands of deletes against a
30-second-capped serialized worker is hours of work a human starts. It only collapses copies that
are **byte-identical** (size *and* date sent) — Mail gives no way to address one specific copy, so
the survivor is whichever one Mail leaves, and identical bytes are what make that safe. Sets that
differ are counted, left alone, and listed under `--verbose`.

Redundant copies go to **Trash**, in small batches, each its own `mail_undo` receipt. Emptying the
Trash is yours to do in Mail.app — nothing here can erase a message.

**It is slow: ~1 minute per duplicate set** against a real IMAP account (Mail's `whose` lookup scans
the whole mailbox), so a big folder is hours. Run it in a terminal you can leave, one mailbox at a
time. It is resumable — the plan is recomputed from Mail's index on every run, so interrupting it
costs nothing and re-running just finds less to do. A set Mail fails to delete is reported, not
retried silently.

### Outbound (send) mode

Sending is **off by default** — the server creates drafts and never sends. Turn it on with:

```sh
macos-apps-mcp allow-send mail    # or: messages / mail,messages / all / off
macos-apps-mcp allow-send         # print the current setting
```

That persists the opt-in and restarts the daemon so it re-registers (registration happens at
import, so a restart is unavoidable — reconnect your MCP client afterward). It is a **CLI
command, not a tool**: the gate is your consent, so the model can neither grant itself sending
nor restart the server out from under your session.

The same choice is available as `MACOS_APPS_ALLOW_SEND` in the environment, which is what a
stdio server reads (a set variable always wins over the persisted toggle):

| Value | Effect |
|---|---|
| unset (default) | no send tools are registered at all |
| `mail` | Mail outbound only (`send_mail`, `reply_all`, `forward_mail`) |
| `mail,messages` | named adapters (comma list) |
| `1` / `true` / `yes` / `all` | every adapter's outbound |

`MACOS_APPS_READ_ONLY` always wins: with both set, no send tools are registered.

Send tools take `dry_run`, which **defaults to `True`** — deliberately inverted from the
id-addressed deletes. A delete targets an item a read already returned; a send *constructs* its
recipient, and a wrong recipient is the failure that matters. The dry run makes no call into Mail
at all and reports the resolved envelope; pass `dry_run=False` to actually send. `reply_all` is
the one exception: its dry run reads (never sends) the original message's actual to/cc
recipients, because that's exactly the recipient set a caller can't predict.

A successful `send_mail` / `reply_all` / `forward_mail` result (`sent: True`) means Mail
**accepted** the message — not that it was delivered. Device-verified: a perfectly-formed message
can sit in Mail's Outbox undelivered for minutes after `send` returns, and a stranded
recipient-less message can jam the outbox so later, valid sends queue behind it and never leave.
Every result also reports `outbox_pending`, Mail's current outbox count; when it's greater than
zero the result carries a `note` explaining that delivery is not confirmed and to check Mail ▸
Outbox.

Run the `doctor` tool to check whether sending is actually enabled — `deployment.outbound` lists
every adapter currently send-enabled (`[]` if none), derived from the same registration logic
above rather than a re-read of the raw env var, so it can never disagree with what got registered;
`deployment.outbound_note` explains the state in prose.

**Under the daemon deployment**, setting `MACOS_APPS_ALLOW_SEND` in an MCP client's config is a
silent no-op: the client's `env` block reaches the shim, not the long-lived daemon process that
reads the variable at import time, and the shipped LaunchAgent plist ships no
`EnvironmentVariables` key. This is exactly why `allow-send` exists — it writes state the daemon
can read (`~/.local/state/macos-apps-mcp/allow_send`, home-pinned so the shell that writes it and
the launchd process that reads it always agree) and survives reboots, unlike `launchctl setenv`.
See [docs/DAEMON.md](docs/DAEMON.md) ("Outbound (send) mode under the daemon").

## Develop

```sh
uv sync
uv run pytest                   # unit tests (mock at the adapter boundary)
uv run pytest -m integration    # real macOS / EventKit / TCC — run manually, never in CI
uv run ruff check .             # lint (config in pyproject.toml)
uv run ruff format .            # format
uv run macos-apps-mcp                  # run the server (stdio)
```

ruff (lint + format, line-length 88) and pytest gate CI — full workflow in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Prior art & credits

macos-apps-mcp builds on prior work — the Apple Mail MCP it draws from, the EventKit/Photos servers it
references, the project that pioneered the unified-Apple-MCP pattern, and FastMCP / PyObjC / the MCP
spec it depends on. See [CREDITS.md](CREDITS.md).
