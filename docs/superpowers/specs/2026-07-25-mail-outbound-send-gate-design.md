# Mail outbound & the send gate (#104, #82, #83) — design

**Milestone:** 0.9.0 — Mail depth & outbound. The first slice; everything outbound depends on it.
**Status:** approved (brainstorming, 2026-07-25).
**Covers:** #104 (granular capability gating), #82 (drafts lifecycle — list/delete only, see Risks),
#83 (opt-in direct send).
**Out of scope:** #86 Messages send (same gate, separate spec), #84 scheduled send, #85 statistics,
and the read/organize issues #75–#81.

## Why

"Never sends" is the deliberate default and it stays the default. But absence of a capability
should be a **gate**, not a ceiling — every other Mail MCP server sends, and automation workflows
legitimately want it. This slice introduces the gate and the first tools behind it, together, so
the gate ships exercised rather than as speculative infrastructure.

## Architecture (no drift)

The gate is one predicate + one decorator in `server.py`, mirroring the existing `_read_only()`
seam: blocked tools are **absent at registration**, never registered-and-erroring. No new error
path, no runtime rejection, nothing for the model to retry against. Adapter methods land in
`adapters/mail.py` and stay Protocol-conformant; `server.py` stays thin dispatch. All native access
via `run_osascript(script, *argv)` — recipients via argv, bodies via `body_file` read as
«class utf8», **never interpolated** (the `run_shortcut` RCE lesson, already the idiom in
`_CREATE_DRAFT`/`_REPLY`).

## The gate (#104)

```python
def _allow_send(adapter: str) -> bool:
    """True when outbound is enabled for `adapter` (#104). READ_ONLY always wins —
    it is the safe-deploy guard and a send tier cannot punch through it."""
    if _read_only():
        return False
    val = os.environ.get("MACOS_APPS_ALLOW_SEND", "").strip().lower()
    if val in ("1", "true", "yes", "all"):
        return True
    return adapter in {p.strip() for p in val.split(",") if p.strip()}


# Outbound leaves this machine — MCP's openWorldHint is exactly that signal.
_SEND_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "openWorldHint": True,
}


def _send_tool(adapter: str, *, snapshot: Snapshotter | None = None):
    """Register an OUTBOUND tool — absent unless MACOS_APPS_ALLOW_SEND names `adapter`.
    ``snapshot``: as on `_write_tool` — pass it on every id-addressed send (#67)."""

    def deco(f):
        if not _allow_send(adapter):
            return f
        _WRITE_TOOLS.add(f.__name__)
        if snapshot is not None:
            _SNAPSHOT_SOURCES[f.__name__] = snapshot
        return mcp.tool(annotations=_SEND_ANNOTATIONS)(_guard(f))

    return deco
```

**Values.** Unset (default) → no send tools. `MACOS_APPS_ALLOW_SEND=mail` → Mail outbound only.
`1` / `true` / `yes` / `all` → every adapter's outbound. Comma lists (`mail,messages`) allow
per-adapter policy — a user may accept Mail send (reviewable, has a Sent record) while refusing
iMessage send (instant, social, no undo).

**Precedence.** `MACOS_APPS_READ_ONLY` wins unconditionally. Both set → no send tools.

**Rejected alternatives.** A single boolean (all-or-nothing; forces two server processes for
mail-only). A three-tier `MACOS_APPS_MODE=read|write|send` (breaking rename of a shipped,
documented env var for zero new capability). A confirm-token two-step (orthogonal to the gate —
it is an in-tool safety and can layer on later without touching this design).

**Audit.** Adding send tools to `_WRITE_TOOLS` gets `AuditMiddleware` for free. `_audit_args`
already truncates strings at 200 chars, so recipients and subject land in the log while bodies are
clipped. Dry-run calls are audited too — noise, but a truthful record of intent and cheaper than a
special case.

## Tool surface

| Tool | Class | Gated by | Signature |
|---|---|---|---|
| `drafts` | read | — | `drafts()` → `list[Pointer]` |
| `delete_draft` | write (destructive) | `READ_ONLY` | `delete_draft(id: str, dry_run: bool = False)` → `dict` |
| `send_mail` | send | `ALLOW_SEND` | `send_mail(to, subject, body, cc=None, bcc=None, html=False, from_address=None, dry_run=True)` → `dict` |
| `reply_all` | send | `ALLOW_SEND` | `reply_all(message_id, body, include_quote=True, dry_run=True)` → `dict` |
| `forward_mail` | send | `ALLOW_SEND` | `forward_mail(message_id, to, body="", dry_run=True)` → `dict` |

`send_draft` is **out of scope** — the on-device spike disproved it (see Risks). #82 closes as
list/delete; `send_mail` covers the compose-and-dispatch use case.

**#82's list/delete half is ungated by `ALLOW_SEND`.** Listing and deleting your own drafts are an
ordinary read and an ordinary local write; only *dispatch* crosses the gate. So `drafts` and
`delete_draft` ship for every user, and `MACOS_APPS_READ_ONLY` still suppresses the delete.

## dry_run — default True on send tools

Send tools default `dry_run=True` and preview; `dry_run=False` actually sends. This is
**deliberately inverted** from `delete_event`/`delete_note`, which default `dry_run=False`, and the
asymmetry is the whole justification:

- A delete is **id-addressed** — the target came from a Pointer a prior read returned, so it is
  already verified.
- A send **constructs** its recipient. Recipient resolution is the step that silently goes wrong.

The preview surfaces exactly that:

```json
{"dry_run": true,
 "would_send": {"to": ["a@b.com"], "cc": [], "bcc": [],
                "from": "andrei@drunik.be", "subject": "Hi",
                "body_chars": 412, "html": false}}
```

**The dry-run path makes NO native call.** It is pure Python over the validated arguments. This is
forced by a device finding (see AppleScript findings): constructing an `outgoing message` can strand
an autosaved copy in Drafts even when the script deletes it, and a *dry* run must not leave
artifacts in the user's mailbox.

`from` therefore reports the caller's `from_address` verbatim, or the literal string
`"(Mail default account)"` when omitted — never a guess. Mail's default sender is **not**
predictable from account order (device check: 4 enabled accounts, first is `andrei@lavrenov.io`,
Mail chose `andrei@lav.ren`), so reporting a computed guess would be a lie. `from_address` exists so
the caller can *choose* rather than predict — `set sender of msg` is verified working.

`from_address` is on `send_mail` only. `reply_all` and `forward_mail` inherit the account of the
original message, which is the correct identity for a thread; overriding it is a separate concern.

**Honest limits.** `dry_run` is a *visibility* mechanism, not a *consent* mechanism: an agentic loop
can simply re-call with `dry_run=False`. Its value is that a wrong recipient becomes visible in the
transcript before anything leaves. Consent is carried by the env gate, the `destructiveHint` +
`openWorldHint` annotations, and the audit log.

All three surviving send tools take `dry_run=True`; none is id-addressed, so none inherits the
deletes' `dry_run=False` default.

## Adapter methods (`adapters/mail.py`)

- `list_drafts() -> list[Pointer]` — messages of `drafts mailbox`, capped at `MAX_MAILS`, reusing
  `_summary()` and `_deeplink()`. On-device probe (2026-07-25) confirmed drafts carry a stable
  integer `id` **and** a `message id` UUID once saved. This corrects the assumption in
  `create_draft`'s docstring ("unsent drafts have no stable id") — true of a freshly opened compose
  window, not of a draft saved to the mailbox. Update that docstring in the same change.
- `delete_draft(ident, dry_run=False) -> dict` — `dry_run=True` returns the Pointer that *would* be
  deleted, no mutation, matching `delete_event`'s shape.
- `send(to, subject, body, cc=None, bcc=None, html=False, from_address=None, dry_run=True) -> dict`
  — `make new outgoing message {visible:false}` + recipients + `send`. `html=True` sets
  `html content` instead of `content`; `from_address` sets `sender of msg`. `dry_run=True` returns
  the preview **without touching Mail at all**.
- `reply_all(message_id, body, include_quote=True, dry_run=True) -> dict` — Mail's native
  `reply … reply to all true`, so `In-Reply-To`/`References` are set by Mail (real threading).
  Reuses `_build_quote` + `sanitize_line` from the existing `reply`.
- `forward(message_id, to, body="", dry_run=True) -> dict` — Mail's `forward` verb, then set
  recipients and send.
- `snapshot(ident) -> Pointer | None` — **new**: `MailAdapter` does not yet satisfy the
  `Snapshotter` Protocol (only calendar, notes, reminders do). `delete_draft` is an id-addressed
  write, so #67 requires before-state capture: resolve the draft by id, return its Pointer, `None`
  if the id no longer resolves. Wired as `@_write_tool(snapshot=_mail)`.

`_send_tool` keeps its optional `snapshot=` parameter even though no surviving send tool is
id-addressed — it costs two lines and keeps #67's invariant intact for #86 and #84.

Atomicity follows `create_draft`'s #44 pattern: if any step after creating the outgoing message
fails, the script deletes the partial message before erroring, so a retry cannot strand a duplicate.

## Errors

Missing/empty recipient, empty subject **and** body, or an unknown draft id → `ValueError` at the
adapter boundary → `ToolError` via `_guard`, carrying an agent-directed remediation. A Mail-side
failure (invalid address, no account configured, Automation denied) → `NativeError` → `ToolError`.
Never an empty dict masquerading as success.

## AppleScript findings (device-verified 2026-07-25, Mail on macOS 25.5)

Every verb below was exercised on device before this plan was written. **Verified working:**
`make new outgoing message {visible:false}` with `to`/`cc`/`bcc` recipients and `html content`;
`set sender of msg to "<address>"`; `reply m opening window no reply to all yes` (returns an
`outgoing message`, subject auto-prefixed `Re:`); `forward m opening window no` (returns an
`outgoing message`, subject auto-prefixed `Fwd:`); `send msg` on a **headless** (`visible:false`)
outgoing message — the classic "send needs a visible window" fear is unfounded here.

Three traps the implementation must avoid:

1. **Autosave stranding.** `delete msg` on an `outgoing message` does not reliably remove Mail's
   autosaved copy from Drafts — reproduced twice, and cleanup needed a reverse-index loop. This is
   why the dry-run path constructs nothing. The real send path is unaffected (`send` consumes the
   message; a device check found no Drafts residue after sending).
2. **`whose` is unreliable on the Drafts mailbox.** `messages of drafts mailbox whose subject is X`
   raised `-1728` ("Can't get item 1 of …") on a draft that demonstrably existed, while
   `whose subject contains X` worked. Address drafts by iterating and comparing `message id`, not
   by a `whose` equality filter.
3. **Deleting while iterating invalidates the collection** (`-1728`). Iterate by index in reverse
   (`repeat with i from n to 1 by -1`), or collect ids first and re-resolve.

**Pre-existing issue, out of scope:** `_CREATE_DRAFT`'s #44 atomicity (`delete msg` on a
post-creation error) is subject to trap 1 — an error path may strand an autosaved draft despite the
rollback. File a separate issue; do not fix it in this branch.

## Risks — resolved

**`send_draft` is NOT implementable. Spike run 2026-07-25 (Mail, macOS 25.5); result: dead end.**
A throwaway draft addressed to the operator's own address was created, saved to Drafts (arriving as
class `message`, id 40371), and `send` was attempted on it:

```
SEND FAILED -1708: Mail got an error: message id 40371 of mailbox "Drafts"
of account id "AE0…" doesn't understand the "send" message.
```

`-1708` is `errAEEventNotHandled`: Mail's `send` verb applies to `outgoing message` only, never to a
message stored in a mailbox. The spike draft was deleted afterwards; no mail was sent.

**Rejected fallbacks.** GUI keystroke scripting (⌘⇧D) — keystroke-free is a standing constraint
(#46). Read-and-recompose (pull the draft's recipients/subject/content into a fresh
`outgoing message`, send that, delete the original) — it silently drops attachments, inline images,
and any hand-tuned formatting, so what gets sent is *not* the draft the human reviewed. A send tool
that quietly alters its payload is worse than no send tool.

**Consequence.** `send_draft` is out of scope. #82 ships as `drafts` + `delete_draft` and closes
with a note recording this dictionary limitation. `send_mail` covers compose-and-dispatch.

## Testing

**Unit** (`uv run pytest`, mocked at the adapter boundary):

- `_allow_send` parse table: unset, `""`, `1`, `true`, `yes`, `all`, `mail`, `mail,messages`,
  `MAIL` (case), stray/empty commas (`mail,,`), unrelated adapter name.
- `READ_ONLY` precedence: `READ_ONLY=1` + `ALLOW_SEND=all` → `_allow_send("mail")` is `False`.
- `dry_run=True` returns a preview and performs **no** native call — assert `run_osascript` is never
  invoked (monkeypatch it to raise). `dry_run=False` dispatches.
- `from_address` is echoed verbatim in the preview; omitted → `"(Mail default account)"`, never a
  computed guess.
- Recipients and bodies reach `run_osascript` via argv/tempfile, never interpolated into the script.
- `tests/test_tool_annotations.py` gains a `send` tier in `_PERMISSION` so the map keeps
  self-enforcing; a new send tool that skips `_send_tool` fails the suite.
- `MailAdapter.snapshot` satisfies `Snapshotter` (extend `tests/test_contracts.py`), and
  `delete_draft` registers a `_SNAPSHOT_SOURCES` entry — so audit before-state cannot be silently
  missed.

**Integration** (`uv run pytest -m integration`, on-device only, **never CI**): every send test
targets the operator's own address. No test ever sends to a third party.

## Verification before done

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Documentation

README gains a `MACOS_APPS_ALLOW_SEND` subsection beside "Read-only mode", stating the default
(off), the accepted values, the `READ_ONLY` precedence rule, and that `dry_run` defaults to `True`
on send tools. CHANGELOG entry under 0.9.0.

## Follow-on specs (0.9.0)

1. #86 Messages send — reuses this gate with `MACOS_APPS_ALLOW_SEND=messages`.
2. #75 / #76 / #77 — Mail reads (rich search, inbox overview, thread view).
3. #78–#81 — Mail organize (mailboxes, flags, trash, attachments).
4. #84 / #85 — scheduled send, statistics + export.
5. #119 — `mail_download_bodies` (moved into this milestone).
