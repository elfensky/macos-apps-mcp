# PR #544 reconciliation — 2026-11-04

Working note for the parent's integration review. Evidence date: 2026-11-04, Europe/Brussels.
Scope: [PR #544](https://github.com/elfensky/macos-apps-mcp/pull/544), branch `night/gsd-standard`.

## Result

- Remote head before the push: `4cc3654cf9b481d2d9ecdebb7b48fdd72b51e1ed`, the head the parent recorded. No other actor changed it.
- The four commits now sit on `origin/develop` at `f91dbed988745ff2d7847907a53d8927b7b2809f`. Their meaning is unchanged.
- One conflict: `.planning/state.json`, modify/delete. Develop changed it in `e90104c` and `55f0a09`. Both commits
  also changed `.planning/STATE.md`, so the canonical Markdown state holds the same update. The resolution keeps the
  deletion. The generated JSON stays untracked and ignored.
- No new `.planning/research/.cache/` file, `docs/ROADMAP.md` reference or `.planning/debug/` reference landed on
  develop since the PR's base `cb8a1a6`. No citation needed a second repair.
- A fifth commit replaces the AGENTS.md keijiban sentence with the vault `publish-page` skill and page-kit recipe.
  It also removes the `.gitignore` comment that called debug records scratch. Debug records stay tracked.
- The AGENTS.md MCP 2 architecture rules are unchanged.
- No `dev:up` was added: this is a stdio/daemon MCP server, and the profile warning does not apply to it.

**eli14:** the PR was a stack of four letters written against last week's filing cabinet. The letters were re-filed
against today's cabinet. One letter threw away a machine-printed index card that the cabinet had updated since. The
handwritten page beside it holds the same update, so the card can still go.

## Publication-policy debate — Claude seat

Question: the page-kit source gate fails on ignored files under `.planning/`. Keep the gate, or exclude runtime files?

Read-only evidence from the ordinary checkout `~/Developer/macos-apps-mcp` (`develop`, `926ec99`):

| File | State | Owner evidence |
|---|---|---|
| `.planning/milestone.lock` | Ignored by `.git/info/exclude`. 145 bytes, written 2026-10-21 00:36. | Phase `04.1`, PID 96619. PID 96619 is not running. The ROADMAP marks 04.1 complete on 2026-10-21. The lock is stale. |
| `05.2-proto/__pycache__/inspect_draft.cpython-314.pyc`, `reply_gui_probe.cpython-314.pyc` | Ignored. Written 2026-11-01 and 2026-11-03. | Python bytecode from the probe scripts beside them. It regenerates on the next run. No content. |
| `02.1-…/.gitkeep` | Untracked, not ignored. One newline byte, 2026-09-24. | The folder already holds ten tracked plan and summary files. The file keeps nothing. |

`git ls-files --others -- .planning/` lists all four files, because `--others` without `--exclude-standard` includes
ignored files. The gate refuses the checkout until they leave it.

**Position: agreement with the parent.** Keep the strict gate and the full-folder hash. No shared publisher change.

- Every file found is stale or regenerable. None is a live session's lock. No runtime-file class exists today that
  a publish must tolerate.
- Excluding runtime files would change a shared rule for four files, and would make the hash skip bytes that sit in
  the source folder. That costs more than it removes.
- Refinement, not an objection: "preserve outside the checkout" is needed only for the lock, as a record of the dead
  session. The bytecode can be deleted. The `.gitkeep` needs its owner's remove-or-commit choice; removal is the
  expected answer because the folder is not empty.
- The PR's old human check ("every line must start with `!!`") does not satisfy the gate. The PR body now says so.

**eli14:** the noticeboard clerk refuses a logbook with loose papers in it. Three loose papers are an old "busy" sign
from a worker who left in October, two pencil shavings, and an empty bookmark. Clear the papers; do not teach the
clerk to ignore loose papers. A rule that ignores papers would also let a real loose page slip through.

## Remaining publication work

This PR does not publish. It is not a technical prerequisite of `publish`. After it merges:

1. The owner clears the four files from the ordinary checkout, after `git pull --ff-only`.
2. The separate vault cutover MR changes the enrollment to `{mode: repo}` and deletes the vault roadmap folder.
3. A session in the ordinary checkout runs the page-kit recipe and uploads the whole project folder once.

## GPT review correction

- The independent GPT review found no blocking defect at `480e966`.
- One P3 citation named the new path in a report explicitly based on commit `8378ab8`.
  That commit contains `docs/ROADMAP.md`, not `docs/landscape.md`.
  The report now retains the historical name and identifies its current name separately.
- Candidate requirements remain represented; the moved debug record is byte-identical.
  The removed JSON contains no unique planning decision. All 26 changed Markdown/HTML files have valid relative Markdown targets.
- Corrected-head validation: 3167 passed, 105 integration tests deselected, seven upstream warnings, 60.09 seconds.
  Ruff lint and formatting passed; 141 files were already formatted. `git diff --check` passed.
