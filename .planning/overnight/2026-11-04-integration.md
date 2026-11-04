# Overnight integration working notes — 2026-11-04

These notes continue the [earlier overnight record](2026-11-03.md).
The [roadmap](../ROADMAP.md) and [state](../STATE.md) hold the current integration status.

## Discovery-error follow-up

- PR #561 merged as `4397787be65afe78b251267dd65131d66dd42fb9` after independent Claude review at `5867870` and six passing CI checks.
- The public FastMCP policy preserves failed discovery as an error. It adds no retry, read deadline, cache policy or private SDK patch.
- The reviewer repeated 64 focused tests and the normal stream smoke. The red check reproduced ten expected failures under the previous policy.
- The reconciliation branch passed 3475 tests, with 105 integration tests deselected and seven upstream warnings. Ruff lint and formatting passed.
- Issue #543 remains open for installed/frontend acceptance and the clipboard observation. The original November 1 cause remains unproved.
- GSD reports 20 phases, nine historical closures, 94 plans and 93 summaries. Zero phases have current verification fingerprints.

## Garage publication

- PR #560 merged as `e94714b7d86ff8aef26a1f08d8cad195e1a64aab`.
- The second publication completed at `2026-11-04T02:08:14Z`. All 15 live HTML paths matched the validated bundle from that commit.
- Project identity and the full planning-folder hash matched `page.json`. The source gate passed before facts and again under the refresh lock.
- The first-publication files remain separate. The new run used a fresh temporary directory and removed the builder's obsolete fixed-commit assertion.
- Publication remains a display operation. It proves no installed build, native write, signing or release acceptance.

## Read-only Trash inventory

Evidence time: `2026-11-04T02:20:21Z`. Physical host: arm64, macOS 27.2.
Selector revision: PR #559 at `872577effc45187d97f1380f932bcb434e82472f`.

- All eight remote account roots had one distinct candidate path. No account root had multiple candidates.
- One `local` store root had no candidate. It was not treated as proof of a remote account's compatibility.
- The query covered every depth, including nested paths and paths inside Trash. Exact decoded aliases collapsed; case and normalization differences stayed distinct.
- The census read only `mailboxes.url` in one SQLite read transaction, with a bounded progress handler and a read-only connection.
- The pinned query builder was extracted from the reviewed commit. Runtime and mailbox-vocabulary blob IDs matched that commit before execution.
- No Message-ID sidecar, message files, native app call, permission change, installation or restart was used. Output omitted account identifiers and mailbox paths.
- The higher-level selector helpers were deliberately avoided: older macOS sidecar setup can read message files and update the Message-ID cache.
- The linked-environment tool was unavailable in this session. No physical Intel inventory was attempted through another route.

The private local evidence files are `mcp-559-local-inventory-classified-20261104.json` and `mcp-559-readonly-inventory.py`.
The physical Intel inventory and localized scratch trash/undo acceptance remain open, with Gmail observations where applicable.
One candidate proves no ambiguity under this selector; it does not prove the native Mail Trash role.
PR #559 remains a draft and is not included in the merged plan count.

**eli14:** The inventory counts drawers labelled “bin” without opening letters.
One label avoids a guessing conflict. It does not prove that Mail uses that drawer.
