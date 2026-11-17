# The roadmap page: one row per release

Design of the content of https://projects.lav.ren/macos-apps-mcp/roadmap/, 2026-11-17. Decided by the owner
(question tool, 2026-11-17): one row per minor release; four eras as context; every open phase in one release, one
release per phase close. Reviewed by two council seats (GPT Astra, Claude Fable 5.2); their critique is folded in.

**eli14:** the page is a shop window. Before, it showed one big box labelled "v0.11.0" and a pile of the workshop's
notes. Now each release is one box on the shelf, in order: the sold boxes go into one drawer, the box in work sits in
front, and the next boxes stand behind it. A card beside the shelf tells the shop's story in four lines. *Today:* the
page reads one more section of the plan. *Later:* the section needs one line of care at each release, or the window
shows an old shelf.

## The page, top to bottom

| Place | Content | Source |
|---|---|---|
| Lede | The project's description | The vault hub's `description` |
| Facts line | `Latest release 0.15.1`, with its date | The writer: the newest `v*` tag |
| eli14 aside | The kitchen analogy | `## eli14` in `.planning/PROJECT.md` |
| Position | "15 of 23 milestones are done. 1 is in work." and the next move | The renderer; `Next:` on the release in work |
| Rows | 0.1–0.15 shipped (title and date), 0.16 in work, 0.17–0.22 and 1.0 to do | `## Releases` in `.planning/ROADMAP.md` |
| Untitled card | "How we got here": the four eras, then "After 1.0" | `### Eras` in that section |
| Blockers | The `Waits for:` lines of the release in work | That section |
| Decisions | The dated owner rules that explain the order | `### Why this order` in that section |
| Sources | ROADMAP.md and STATE.md at the plan commit; STATE.md holds the full decision log | The writer |

The writer (`project-pages.py write --repo`, vault page-kit § Releases) reads the section. It refuses an open phase
in no release or in two, an unknown phase, and a `vX.Y.0` tag without its shipped line. A release cut marks its line
shipped (`docs/RELEASING.md` § Cutting a release).

## Why each choice

- **One row per minor release.** A row is what a user gets, and "a minor bump marks a change of theme"
  (`docs/landscape.md` § Release cadence). The renderer folds the shipped rows, so 15 shipped releases cost one line.
- **Eras as context, not as rows.** The renderer shows one list in plan order (layout decision, 2026-11-06); a second
  row level needs a renderer change. The eras follow what changed for a user: 0.8 (one signed app holds the
  permissions), 0.11 (the planned rebuild after the review of 2026-08-28), 0.16 (the MCP 2 core and the road to
  launch). 0.14.2 is no boundary: a patch release in the middle of the 0.14 theme.
- **One section in ROADMAP.md.** One place to edit, next to the phases it names. GSD's `validate consistency`,
  `roadmap validate` and `roadmap analyze` give the same output with the section (tested 2026-11-17). Not tested:
  GSD's write workflows, such as milestone close, which archives ROADMAP.md.
- **Shipped rows without items.** The renderer shows no summary and no items on a done row; the title carries it.
- **Row texts from the changelog.** Each shipped title and summary restates its CHANGELOG.md section, narrowed to
  what that section says. The 0.10 notes stand under the 0.11.0 heading of CHANGELOG.md; the tag message of v0.10.0
  is "Mail complete".

## Rejected

- **Eras as rows** (three era rows, one plan row, one v2 row): needs a new data field and a renderer change, and keeps
  the plan as one large "10 of 21 phases" row.
- **Each release as a GSD milestone:** rebuilds the live GSD milestone through GSD's workflows, and 0.1–0.11 have no
  GSD phases to archive.
- **Rows from CHANGELOG.md headings and tags:** four sources for one page, and 15 public changelog headings rewritten.
- **A v2 row and an "open work" row:** neither is a release; both distort the counts. v2 stands in the eras card.

## Open

- The phase names on the milestone pages still carry tracker numbers and kind-of-work words ("Bug fixes — … (#455)").
  A rename to results goes through `/gsd-phase`.
- The calendar labels of the 15 releases of June–July overlap (keijiban).
- The hub description is the vault's: "Lets an AI assistant use Mail, Calendar, Reminders, Notes, Photos and five more
  Mac apps; a delete, move or send shows a preview first."
