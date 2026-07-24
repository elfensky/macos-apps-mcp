# Music adapter (#69) — design

**Milestone:** 0.8.0 — New adapters & expansion. The last feature for 0.8.0.
**Status:** approved (brainstorming, 2026-07-24). On-device AppleScript extractors verified
(Music 1.6.5).

## Why

T4 of the closed expansion epic (#22). Music has a rich AppleScript dictionary; playback control,
"what's playing", and playlist ops are daily-useful and low-risk — **no personal-data writes**. One
active competitor (epheterson/applemusic-mcp) with thin coverage; its #26 failure was smart-punctuation
search, which this design fixes.

## Architecture (no drift)

One adapter module `macos_apps_mcp/adapters/music.py`, Protocol-conformant, thin-dispatched from
`server.py`. Native access via `runtime.run_native()` → `run_osascript(script, *argv)` — user input
**only ever via argv**, never interpolated (the `run_shortcut` RCE lesson). Framed records reuse the
`mail.py` idiom (delimiter-joined fields + `stripFraming` on any free-text field, `¬` line continuation
≤88 cols). No business logic in the tool layer.

## Tool surface (6 tools)

| Tool | Class | Signature | Returns |
|---|---|---|---|
| `music_search` | read | `music_search(query: str)` | `list[Pointer]` — matching library tracks **and** playlists |
| `now_playing` | read | `now_playing()` | `dict` — player state + current track |
| `music_control` | additive | `music_control(action: str)` — `play\|pause\|playpause\|next\|previous` | `dict` (resulting state) |
| `play_playlist` | additive | `play_playlist(id: str)` | `dict` (resulting state) |
| `set_volume` | additive | `set_volume(level: int)` — 0–100 | `dict` |
| `set_mode` | additive | `set_mode(mode: str, on: bool)` — mode `shuffle\|repeat` | `dict` |

Playlist discovery is folded **into** `music_search` (no separate `playlists` tool) — one search
returns both tracks and the playlists whose ids feed `play_playlist`.

## Reads — the Pointer contract

### `music_search`

- **One bulk Apple Event** fetches parallel lists (`name`/`artist`/`album`/`persistent ID` of every
  track of `library playlist 1`; `name`/`persistent ID` of every user playlist), then **Python-side
  `fold_text` filtering** (#64). This is the #26 smart-punctuation fix: Music's native `search` can't
  match ASCII `'` against a library's curly `'` — folding **both** query and candidate fixes it. Fold
  THEN strip the query (notes/shortcuts idiom): a query of only fold-away chars must not become a
  truthy `" "` and filter to space-containing names — empty query = "list all" (bounded).
- Bounded to `MAX_MUSIC_RESULTS = 50` (tracks + playlists combined; pointers-not-payload).
- Each `Pointer`:
  - `id` = **persistent ID** — stable across renames; the handle `play_playlist` consumes for playlists.
  - `summary` = `"Track — Artist (Album)"` for tracks / `"Playlist (N tracks)"` for playlists, via
    `clean_summary`.
  - `deeplink` = `""`. Local library items have **no reliable `music://` URL** (verified: local tracks
    carry no catalog id). Honest-empty, exactly like `shortcuts` run-pointers and degraded `safari`
    tabs. `folder` / `reason` unused.

Performance ceiling: the bulk parallel-list read is one Apple Event regardless of library size; for a
very large library it returns a few long lists (fast — one round-trip, verified on 75 tracks). If it
ever drags, native `search lib for query` is the fallback (loses cross-side folding). `# ponytail:`
comment marks the ceiling + upgrade path in code.

### `now_playing`

- `{state, track, artist, album, id, position, duration}` when `player state` ∈ {playing, paused}.
- `{state: "stopped"}` otherwise — current-track access **errors** when stopped (verified), so it is
  guarded (`try` in AppleScript, or state-checked before access).

## Writes, safety, wiring

- All 4 actions are `@_additive_tool` (readOnlyHint=false, destructiveHint=false): reversible, no data
  loss, no personal-data write — they mutate **transient player state**, not stored records. Stripped in
  `MACOS_APPS_READ_ONLY` (all writes are). **No `snapshot`** — not id-addressed mutations of stored
  records, nothing to audit-reverse. Still audit-logged automatically by `AuditMiddleware`.
- `music_control`: verb validated against a fixed set; unknown verb → `ValueError` → `ToolError`.
- `set_volume`: validated/clamped to 0–100 (`ValueError` outside range).
- `set_mode`: `mode` validated `shuffle|repeat`. `shuffle` → `shuffle enabled` (boolean). `repeat` is
  Music's **tri-state** `song repeat` (`off`/`one`/`all`) mapped from the boolean `on`: `on=true` →
  `all`, `on=false` → `off` (the two daily-useful states; `one` is out of scope, revisit if requested).
- `play_playlist`: targets by **persistent ID** — `play (first playlist whose persistent ID is <id>)`.
  Id-addressed per the disambiguation rule (contracts.py) — a write never auto-picks among name matches.
  Unknown id → `ValueError` naming the failure ("no playlist with id …; call music_search").
- `doctor`: add `"Music"` to `doctor._AUTOMATION_APPS` so the Automation probe covers it.

## Testing

- **Unit** (mock at the adapter boundary, Protocol fakes): parsing of framed track/playlist records,
  `fold_text` smart-punctuation matching (curly ↔ straight quotes, diacritics), `MAX_MUSIC_RESULTS`
  bound, verb/volume/mode validation, `now_playing` stopped-vs-playing shape. No native calls.
- **`tests/test_tool_annotations.py`**: add the 6 tools to the `_PERMISSION` map (1 read set + 4
  additive + `now_playing`/`music_search` read) — the self-enforcing annotation guard.
- **Integration** (`-m integration`, on-device only, **never CI**): real `now_playing`, `music_control`
  play→pause round-trip, `set_volume` restore-after, `play_playlist` against a known id. Marked so
  audible/stateful tests run manually.

## Acceptance (from #69)

- [ ] Pointer contract on all reads (`music_search` → `list[Pointer]`; ids = persistent IDs).
- [ ] Actions stripped in read-only mode (`@_additive_tool` under `MACOS_APPS_READ_ONLY`).
- [ ] Integration-marked playback tests.
- [ ] Smart-punctuation matching (#26 fixed via cross-side `fold_text`).
- [ ] `doctor` probes Music.

## Out of scope (YAGNI)

- Apple Music catalog / web deeplinks (local library has no catalog id).
- Rating/love, add-to-playlist, AirPlay device selection, EQ, track scrubbing (`player position` set),
  queue manipulation. Additive playback + search covers the daily-useful surface; revisit if requested.
