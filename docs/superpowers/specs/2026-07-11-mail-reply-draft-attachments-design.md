# Mail reply / draft / attachment surface — design

**Date:** 2026-07-11
**Milestone:** 0.5.0 — Native data planes
**Issues:** #42, #43, #44, #45, #46
**Status:** approved (design), pre-implementation

## Context

mac-mcp's mail adapter (`mac_mcp/adapters/mail.py`, Mail.app via osascript) today does
inbox search (`get_pointers`), body-by-id (`get_body`), and a `create_draft` that opens a
compose window for human review. There is **no send path anywhere** and never will be — a
wrong-recipient/address-leak send is the ecosystem's most dangerous mail action.

Issues #42–#46 came from real pain with earlier breadth-first mail MCPs and ask mac-mcp to
grow a small, solid reply/draft/attachment surface:

- **#42** — a reply that quotes the original and threads correctly (In-Reply-To/References),
  not just a `Re:` subject.
- **#43** — return something to identify the created draft (subject search collides).
- **#44** — a failed reply must not strand a partial draft (which caused duplicate drafts).
- **#45** — verify a draft's attachment programmatically (`list_email_attachments` had no
  mailbox param; `has_attachments` was blind to Drafts).
- **#46** — "open draft for review" must not depend on Accessibility/keystroke automation.

## Spike results (real Mail, 2026-07-11)

Andrei's directive: *test all approaches, pick the most stable.* Findings:

| Approach | Threading headers | Body set (no keystrokes) | Editable+sendable draft | Cleanup |
|---|---|---|---|---|
| **A — native `reply` verb** | Mail sets them natively on send | ✅ `content` settable | ✅ real outgoing message | ✅ `delete` works |
| B — `make new outgoing` + header | ❌ **impossible** (no `headers` element on an outgoing message) | ✅ | ✅ | ✅ |
| C — `.eml` + `open` (#46's mechanism) | in the file | n/a | ❌ **read-only viewer** (`outgoing_count=0`, not in Drafts) | n/a |

**Decision: Approach A (native `reply` verb).** It is the only mechanism that threads
(B is impossible; C can't produce a sendable draft), its body is settable without
keystrokes, and the draft is deletable for atomic cleanup. **Approach A satisfies #42,
#44, and #46 together**, and the `.eml` path (#46's proposed mechanism) is **dropped** —
it cannot produce an editable/sendable draft on this Mail. This deviates from the roadmap
prompt's stated `.eml` preference; the evidence drives it.

Two limits the spike exposed:
- Mail's auto-quote is **not** visible via the `content` property (reads empty) → we build
  the quote block ourselves.
- `source` is **not readable** on an unsent `outgoing message` → threading headers cannot
  be unit-proved; they only exist post-send.

## Decisions (locked with Andrei)

1. **Reply mechanism:** Mail's native `reply` verb; `.eml` dropped.
2. **#43/#44:** atomic creation (delete-on-error, in-script) + return an honest locator
   dict — **no** fabricated/session-local id.
3. **#45:** address by **mailbox + subject query** (works for Drafts; reuses
   `system_mailbox_names`); return structured attachment info.
4. **Reply scope:** **sender only**, not reply-all (recipient-leak footgun); a `reply_all`
   flag can be added later if needed.
5. **Never send:** no `send` verb anywhere; reply is draft-and-open only.
6. **Build order:** safe/independent first (#45, then #43/#44 on `create_draft`), then the
   threading cluster (#42/#46 `reply`).

## Architecture

All logic in `mac_mcp/adapters/mail.py` (osascript templates + thin Python), thin-dispatched
from `mac_mcp/server.py`. No new dependencies. Reuses `system_mailbox_names`, `_deeplink`,
`run_osascript` (with `--`), `clean_summary`/`clean_body`, and the `\x1f`/`\x1e` control-char
framing pattern (from notes) for fields that may contain arbitrary text. All user input via
argv / tempfile — never interpolated. All templates carry `with timeout`.

### Component 1 — `#45` `list_attachments(mailbox, query)` (READ; built first)

- Resolve `mailbox` (canonical `inbox`/`sent`/`drafts`/`trash`/`junk`) via
  `system_mailbox_names`, trying each localized candidate until Mail resolves one — works on
  a non-English Mac and on **Drafts** (no message-id needed).
- osascript walks messages of that mailbox matching the subject `query`, emitting per
  message: subject + each attachment's `name`, `file size`, `downloaded` flag, framed with
  `\x1f` (between fields) / `\x1e` (between records).
- Python parses into a bounded structured result:
  `[{ "summary": <subject>, "attachments": [{ "name", "size", "downloaded" }] }]`,
  capped at `MAX_MAILS`, every field hygiene-cleaned.
- Answers "did LOGO.zip actually attach to my draft?" without opening Mail.
- **Note:** this covers #45's `list_email_attachments`-with-mailbox need. The separate
  "`has_attachments` filter in `search_emails`" sub-ask is satisfied functionally by this
  dedicated read rather than by bolting a flag onto `get_pointers`.

### Component 2 — `#43/#44` atomic `create_draft` + locator

- **Atomic (#44):** the osascript holds the outgoing-message ref; on **any** failure after
  creation it `delete`s that ref before re-raising, so no partial draft is stranded and a
  retry can't produce a duplicate.
- **Return (#43):** `create_draft` returns a status dict instead of `None`:
  `{ "created": True, "subject": <subject>, "mailbox": "Drafts",
     "note": "unsent drafts have no stable id; find it in Drafts" }`.
  Honest about the no-stable-id constraint (Mail stamps the Message-ID only on send).
- Behavior change: update the `server.py` tool, its docstring, `test_tool_annotations`
  (`_ADDITIVE_TOOLS` / permission map already list `create_draft`), and the unit test.

### Component 3 — `#42/#46` `reply(message_id, reply_body, include_quote=True)`

1. Locate the original by its cited RFC822 `message_id` (same lookup `get_body` uses).
2. `set r to reply <original>` → a real `outgoing message`; Mail owns the
   In-Reply-To/References linkage.
3. `set content of r` = `reply_body` + (if `include_quote`) a self-built quote block:
   `On <date>, <sender> wrote:` then the original body `> `-prefixed. Bounded by the
   existing hygiene caps so a huge original can't bloat the draft.
4. Open the compose window for the human to review and send. **Never sends.** No keystrokes,
   no `.eml` → #46's keystroke-free goal met.
5. **Atomic (#44):** on any failure after creation, `delete r` before re-raising.
6. Sender-only (no reply-all).

## Error handling

- Missing/empty `message_id`, `reply_body`, `mailbox`, or `query` → `ValueError` with a
  clear message (mirrors existing adapter guards).
- Unknown canonical mailbox → `ValueError` (via `system_mailbox_names`).
- Original message not found for reply → `NativeError` ("no inbox message with that message
  id"), mirroring `get_body`.
- Any osascript failure mid-create → the template deletes the partial ref, then the Python
  layer surfaces the typed runtime error via `server._guard`.
- `missing value` coercions guarded exactly as the existing id/body paths do.

## Testing

Unit (mock `run_osascript`, no Mail):
- `list_attachments`: parse fake `\x1f`/`\x1e` payloads → structured result; unknown mailbox
  raises; cap respected; hygiene applied.
- `create_draft`: forced-failure payload → assert the cleanup `delete` was issued; assert the
  returned locator dict shape; empty recipient raises.
- `reply`: assert the script targets the right message-id, body = `reply_body` + quote,
  `include_quote=False` omits the quote, forced-failure issues the cleanup `delete`, empty
  args raise.

`@pytest.mark.integration` (real Mail, not in CI):
- `list_attachments`: create a draft with an attachment → list it from Drafts → assert the
  attachment name appears; forced-error path leaves nothing behind.
- `reply`: create a reply draft to a real message → assert it exists **unsent** as an
  outgoing message carrying our body+quote → delete it → confirm nothing was sent.
- **Manual** (documented in the PR's "needs manual verification"): send ONE test reply to
  yourself, then assert the *received* copy's `source` contains `In-Reply-To`/`References` —
  the only way to prove threading, since headers don't exist pre-send.

## Known risks (to resolve during implementation, not hand-waved)

- **Locating a message by message-id:** in the spike, `... whose message id is X` returned
  empty for a just-read message. `get_body` uses the same pattern, so this may be a
  pre-existing quirk (unified-inbox vs per-account, or id round-tripping). Verify a reliable
  lookup before building `reply` on it; if flaky, that is its own fix.
- **Setting `content` on an open compose window:** confirm the window reflects the
  programmatically-set body (may require setting content before opening the window).

## Out of scope / deferred

- **No send path.** Ever.
- **Reply-all**, rich-text/HTML bodies, forwarding — not now.
- **Contacts/mail/messages fold** (#64) — separate concern.
- The `.eml` mechanism — dropped per the spike.
