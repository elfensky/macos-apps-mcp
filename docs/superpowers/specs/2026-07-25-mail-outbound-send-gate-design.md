# Mail outbound & the send gate (#104, #82, #83) — design

**Milestone:** 0.9.0 — Mail depth & outbound. The first slice; everything outbound depends on it.
**Status:** approved (brainstorming, 2026-07-25).
**Covers:** #104 (granular capability gating), #82 (drafts lifecycle), #83 (opt-in direct send).
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
| `send_mail` | send | `ALLOW_SEND` | `send_mail(to, subject, body, cc=None, bcc=None, html=False, dry_run=True)` → `dict` |
| `reply_all` | send | `ALLOW_SEND` | `reply_all(message_id, body, include_quote=True, dry_run=True)` → `dict` |
| `forward_mail` | send | `ALLOW_SEND` | `forward_mail(message_id, to, body="", dry_run=True)` → `dict` |
| `send_draft` | send | `ALLOW_SEND` | `send_draft(id: str, dry_run: bool = True)` → `dict` — **spike-gated, see Risks** |

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
                "from": "andrei@lav.ren", "subject": "Hi",
                "body_chars": 412, "html": false}}
```

`from` requires resolving Mail's sending account — one extra osascript read on the dry-run path.

**Honest limits.** `dry_run` is a *visibility* mechanism, not a *consent* mechanism: an agentic loop
can simply re-call with `dry_run=False`. Its value is that a wrong recipient becomes visible in the
transcript before anything leaves. Consent is carried by the env gate, the `destructiveHint` +
`openWorldHint` annotations, and the audit log.

`send_draft(id)` is id-addressed like the deletes, but keeps `dry_run=True` because it still
dispatches outbound; its preview reports the draft's resolved recipients and subject.

## Adapter methods (`adapters/mail.py`)

- `list_drafts() -> list[Pointer]` — messages of `drafts mailbox`, capped at `MAX_MAILS`, reusing
  `_summary()` and `_deeplink()`. On-device probe (2026-07-25) confirmed drafts carry a stable
  integer `id` **and** a `message id` UUID once saved. This corrects the assumption in
  `create_draft`'s docstring ("unsent drafts have no stable id") — true of a freshly opened compose
  window, not of a draft saved to the mailbox. Update that docstring in the same change.
- `delete_draft(ident, dry_run=False) -> dict` — `dry_run=True` returns the Pointer that *would* be
  deleted, no mutation, matching `delete_event`'s shape.
- `send(to, subject, body, cc=None, bcc=None, html=False, dry_run=True) -> dict` —
  `make new outgoing message` + recipients + `send`. `html=True` sets `html content` instead of
  `content`; one branch in the script.
- `reply_all(message_id, body, include_quote=True, dry_run=True) -> dict` — Mail's native
  `reply … reply to all true`, so `In-Reply-To`/`References` are set by Mail (real threading).
  Reuses `_build_quote` + `sanitize_line` from the existing `reply`.
- `forward(message_id, to, body="", dry_run=True) -> dict` — Mail's `forward` verb, then set
  recipients and send.
- `send_draft(ident, dry_run=True) -> dict` — spike-gated.
- `snapshot(ident) -> Pointer | None` — **new**: `MailAdapter` does not yet satisfy the
  `Snapshotter` Protocol (only calendar, notes, reminders do). `delete_draft` and `send_draft` are
  id-addressed writes, so #67 requires before-state capture: resolve the draft by id, return its
  Pointer, `None` if the id no longer resolves. Wired as `@_write_tool(snapshot=_mail)` and
  `@_send_tool("mail", snapshot=_mail)`.

Atomicity follows `create_draft`'s #44 pattern: if any step after creating the outgoing message
fails, the script deletes the partial message before erroring, so a retry cannot strand a duplicate.

## Errors

Missing/empty recipient, empty subject **and** body, or an unknown draft id → `ValueError` at the
adapter boundary → `ToolError` via `_guard`, carrying an agent-directed remediation. A Mail-side
failure (invalid address, no account configured, Automation denied) → `NativeError` → `ToolError`.
Never an empty dict masquerading as success.

## Risks

**`send_draft` is not confirmed implementable.** Mail's `send` verb is typed for `outgoing message`;
whether it accepts a stored `message` from the Drafts mailbox is unverified — `sdef` requires Xcode,
which is absent on this machine, so the dictionary could not be read. GUI keystroke scripting
(⌘⇧D) is **not** an acceptable fallback (keystroke-free, #46).

**Resolution: an on-device spike runs before the implementation plan is written.** Create a draft
addressed to the operator's own address, save it, and attempt `send` on the stored message. If it
fails, `send_draft` drops from scope, #82 closes as list/delete only, and `send_mail` covers the
use case. This is settled before task-writing, not discovered mid-implementation.

## Testing

**Unit** (`uv run pytest`, mocked at the adapter boundary):

- `_allow_send` parse table: unset, `""`, `1`, `true`, `yes`, `all`, `mail`, `mail,messages`,
  `MAIL` (case), stray/empty commas (`mail,,`), unrelated adapter name.
- `READ_ONLY` precedence: `READ_ONLY=1` + `ALLOW_SEND=all` → `_allow_send("mail")` is `False`.
- `dry_run=True` returns a preview and performs **no** native call; `dry_run=False` dispatches —
  asserted against `Protocol` fakes.
- Recipients and bodies reach `run_osascript` via argv/tempfile, never interpolated into the script.
- `tests/test_tool_annotations.py` gains a `send` tier in `_PERMISSION` so the map keeps
  self-enforcing; a new send tool that skips `_send_tool` fails the suite.
- `MailAdapter.snapshot` satisfies `Snapshotter` (extend `tests/test_contracts.py`), and
  `delete_draft`/`send_draft` register a `_SNAPSHOT_SOURCES` entry — so audit before-state cannot
  be silently missed.

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
