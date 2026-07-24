# Music Adapter (#69) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Music.app adapter — bounded library/playlist search, now-playing, and additive playback control (play/pause/skip, play-playlist-by-id, volume, shuffle/repeat) — as the last feature for the 0.8.0 milestone.

**Architecture:** One Protocol-conformant module `macos_apps_mcp/adapters/music.py` reached via osascript (Automation TCC). Reads are uniform → `list[Pointer]` (`music_search`) plus one enumeration read (`now_playing`); writes are additive, low-stakes player-state changes. All native access via `runtime.run_osascript(script, *argv)` — user input **only ever via argv**, never interpolated. Framed records reuse the shared `text.STRIP_FRAMING` / `split_framed` contract (#68). Smart-punctuation matching via `text.fold_text` (#26/#64). Thin dispatch in `server.py`.

**Tech Stack:** Python 3.12+, FastMCP, `uv`, `ruff`, `pytest`. AppleScript via `osascript`.

## Global Constraints

- **Thin dispatch:** tools in `server.py` are thin wrappers over `MusicAdapter`; no business logic in the tool layer.
- **argv only:** every user value (`query`, `action`, playlist `id`, `level`, `mode`) reaches AppleScript through `run_osascript(script, *args)` — NEVER string-interpolated (the `run_shortcut` RCE lesson).
- **Framing contract (#68):** import `US`, `RS`, `STRIP_FRAMING`, `split_framed` from `macos_apps_mcp.text`. Do NOT hard-code `\x1f`/`\x1e` or re-declare the strip handler.
- **Pointer contract:** reads return `Pointer(id, summary, deeplink)`. `id` = persistent ID (stable). `deeplink = ""` — local library items have no reliable `music://` URL (verified on-device). Summaries via `clean_summary`.
- **Permission classification (#57):** `music_search` + `now_playing` are `@_read_tool`; `music_control`, `play_playlist`, `set_volume`, `set_mode` are `@_additive_tool` (readOnlyHint=false, destructiveHint=false). No `snapshot=` (transient state, nothing to audit-reverse).
- **Docstrings must name the permission:** every Music tool docstring must contain the word **"Automation"** (enforced by `tests/test_tool_annotations.py`).
- **Bounds:** `MAX_MUSIC_RESULTS = 50`.
- **Verify before done (per task):** `uv run pytest` && `uv run ruff check .` && `uv run ruff format --check .`. Integration tests (`-m integration`) run on-device only, NEVER in CI.
- **Line length 88; ruff rules E,F,I,UP,B,SIM.** Use `¬` line-continuation in AppleScript to stay ≤88 cols.

All AppleScript templates below were verified on-device (Music 1.6.5, 2026-07-24). The framed search
emits track records `T␟name␟artist␟album␟pid␞` and playlist records `P␟name␟count␟pid␞`.

---

### Task 1: Read core — `music.py` + `music_search`

**Files:**
- Create: `macos_apps_mcp/adapters/music.py`
- Test: `tests/test_music.py`

**Interfaces:**
- Consumes: `Pointer` (contracts), `run_osascript` (runtime), `US`, `RS`, `STRIP_FRAMING`, `split_framed`, `fold_text`, `clean_summary`, `sanitize_line` (text).
- Produces:
  - `MAX_MUSIC_RESULTS: int = 50`
  - `_SEARCH: str` (AppleScript, no argv)
  - `MusicAdapter().get_pointers(query: str = "") -> list[Pointer]`
  - module-global name `run_osascript` (imported at module top so tests monkeypatch `music.run_osascript`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_music.py`:

```python
"""Unit tests for the Music adapter — mock at the osascript boundary (no native calls)."""

from __future__ import annotations

import pytest

import macos_apps_mcp.adapters.music as music
from macos_apps_mcp.adapters.music import MusicAdapter
from macos_apps_mcp.text import RS, US


def _rec(*fields: str) -> str:
    return US.join(fields)


def test_music_search_parses_track_and_playlist(monkeypatch):
    raw = (
        RS.join(
            [
                _rec("T", "Don't Stop", "The Band", "Greatest", "TID1"),
                _rec("P", "Chill", "12", "PID1"),
            ]
        )
        + RS
    )
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: raw)
    ptrs = MusicAdapter().get_pointers("")
    assert ptrs[0].id == "TID1"
    assert ptrs[0].summary == "Don't Stop — The Band (Greatest)"
    assert ptrs[0].deeplink == ""
    assert ptrs[1].id == "PID1"
    assert ptrs[1].summary == "Chill (12 tracks)"


def test_music_search_folds_smart_punctuation(monkeypatch):
    # library stores a curly apostrophe (U+2019); an ASCII query must still match (#26)
    raw = _rec("T", "Don’t Stop", "Band", "Alb", "TID1") + RS
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: raw)
    assert MusicAdapter().get_pointers("don't stop")  # ASCII ' matches U+2019


def test_music_search_filters_by_query(monkeypatch):
    raw = (
        RS.join(
            [_rec("T", "Sunrise", "A", "X", "1"), _rec("T", "Moonset", "B", "Y", "2")]
        )
        + RS
    )
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: raw)
    ptrs = MusicAdapter().get_pointers("moon")
    assert [p.id for p in ptrs] == ["2"]


def test_music_search_bounds_results(monkeypatch):
    raw = RS.join(_rec("T", f"t{i}", "a", "b", f"ID{i}") for i in range(120)) + RS
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: raw)
    assert len(MusicAdapter().get_pointers("")) == music.MAX_MUSIC_RESULTS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_music.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'macos_apps_mcp.adapters.music'`

- [ ] **Step 3: Write the implementation**

Create `macos_apps_mcp/adapters/music.py`:

```python
"""Music adapter — Music.app via osascript (Automation TCC). Library/playlist search,
now-playing, and additive playback control (#69).

Reads: ``music_search`` returns matching library tracks AND user playlists as Pointers
(id = persistent ID; deeplink = "" — a local library item has no reliable ``music://``
URL); ``now_playing`` returns the current player state. Actions (additive, reversible,
no personal-data write): play/pause/skip, play a playlist by id, set volume, set
shuffle/repeat. Smart-punctuation-insensitive matching via ``fold_text`` (#26/#64). All
user input goes via argv (no interpolation); the bulk parallel-list track read is ONE
Apple Event, so it scales past a small library.
"""

from __future__ import annotations

from ..contracts import Pointer
from ..runtime import run_osascript
from ..text import (
    RS,
    STRIP_FRAMING,
    US,
    clean_summary,
    fold_text,
    sanitize_line,
    split_framed,
)

MAX_MUSIC_RESULTS = 50  # pointers-not-payload: cap tracks + playlists combined

# One Apple Event pulls parallel lists of ALL track fields (scales — no per-track round
# trips), then each free-text field passes through the shared stripFraming handler so a
# name containing US/RS bytes can't desync the parser. Records: a leading type tag
# ("T" track / "P" playlist), then US-joined fields, RS-terminated. Verified on-device.
_SEARCH = (
    STRIP_FRAMING
    + """

set us to character id 31
set rs to character id 30
set out to ""
with timeout of 120 seconds
tell application "Music"
  set lib to library playlist 1
  set ns to (get name of every track of lib)
  set ars to (get artist of every track of lib)
  set als to (get album of every track of lib)
  set pids to (get persistent ID of every track of lib)
  repeat with i from 1 to (count of ns)
    set out to out & "T" & us & (my stripFraming(item i of ns)) & us & ¬
      (my stripFraming(item i of ars)) & us & ¬
      (my stripFraming(item i of als)) & us & (item i of pids) & rs
  end repeat
  repeat with p in (get user playlists)
    set out to out & "P" & us & (my stripFraming(name of p)) & us & ¬
      ((count of tracks of p) as text) & us & (persistent ID of p) & rs
  end repeat
end tell
end timeout
return out"""
)


def _track_pointer(name: str, artist: str, album: str, pid: str) -> Pointer:
    summary = name
    if artist:
        summary = f"{name} — {artist}"
    if album:
        summary = f"{summary} ({album})"
    return Pointer(id=pid, summary=clean_summary(summary), deeplink="")


def _playlist_pointer(name: str, count: str, pid: str) -> Pointer:
    return Pointer(id=pid, summary=clean_summary(f"{name} ({count} tracks)"), deeplink="")


def _parse_search(raw: str) -> list[tuple[Pointer, str]]:
    """Parse the framed search payload into (Pointer, fold-key) pairs. The fold-key is
    the searchable text folded (#64) so the Python-side filter is diacritic/smart-punct
    insensitive on BOTH sides — the #26 fix. Malformed/short records are skipped."""
    out: list[tuple[Pointer, str]] = []
    for rec in split_framed(raw):
        if rec[0] == "T" and len(rec) >= 5:
            _, name, artist, album, pid = rec[:5]
            out.append(
                (_track_pointer(name, artist, album, pid),
                 fold_text(f"{name} {artist} {album}"))
            )
        elif rec[0] == "P" and len(rec) >= 4:
            _, name, count, pid = rec[:4]
            out.append((_playlist_pointer(name, count, pid), fold_text(name)))
    return out


class MusicAdapter:
    def get_pointers(self, query: str = "") -> list[Pointer]:
        """query: optional name/artist/album substring (empty lists all, bounded).

        Fold THEN strip the query (the notes/shortcuts idiom, #64 review): a query of
        only fold-away chars must not become a truthy " " and filter to space-containing
        names — an empty query means "list all".
        """
        parsed = _parse_search(run_osascript(_SEARCH))
        q = fold_text(query).strip()
        if q:
            parsed = [(p, key) for p, key in parsed if q in key]
        return [p for p, _ in parsed[:MAX_MUSIC_RESULTS]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_music.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint + format, then commit**

```bash
uv run ruff check macos_apps_mcp/adapters/music.py tests/test_music.py
uv run ruff format macos_apps_mcp/adapters/music.py tests/test_music.py
git add macos_apps_mcp/adapters/music.py tests/test_music.py
git commit -m "feat(music): #69 music_search — library/playlist search as Pointers"
```

---

### Task 2: `now_playing`

**Files:**
- Modify: `macos_apps_mcp/adapters/music.py`
- Test: `tests/test_music.py`

**Interfaces:**
- Consumes: `US`, `sanitize_line`, `STRIP_FRAMING`, `run_osascript`.
- Produces:
  - `_NOW_PLAYING: str`
  - `MusicAdapter().now_playing() -> dict` — `{state, track, artist, album, id, position, duration}` when playing/paused; `{"state": "stopped"}` (or `{"state": <other>}`) otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_music.py`:

```python
def test_now_playing_stopped(monkeypatch):
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: "stopped")
    assert MusicAdapter().now_playing() == {"state": "stopped"}


def test_now_playing_playing(monkeypatch):
    raw = US.join(["playing", "Song", "Artist", "Album", "TID", "5.0", "200.0"])
    monkeypatch.setattr(music, "run_osascript", lambda *a, **k: raw)
    r = MusicAdapter().now_playing()
    assert r["state"] == "playing"
    assert r["track"] == "Song"
    assert r["artist"] == "Artist"
    assert r["album"] == "Album"
    assert r["id"] == "TID"
    assert r["position"] == "5.0"
    assert r["duration"] == "200.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_music.py -k now_playing -v`
Expected: FAIL — `AttributeError: 'MusicAdapter' object has no attribute 'now_playing'`

- [ ] **Step 3: Write the implementation**

In `macos_apps_mcp/adapters/music.py`, add the template after `_SEARCH`:

```python
# now-playing: player state, plus the current track's fields when not stopped. Reading
# `current track` ERRORS when stopped (verified on-device), so it is guarded by the
# state check. STRIP_FRAMING protects the free-text fields; US-joined, no records.
_NOW_PLAYING = (
    STRIP_FRAMING
    + """

set us to character id 31
set out to ""
with timeout of 120 seconds
tell application "Music"
  set pstate to (player state as text)
  set out to pstate
  if pstate is not "stopped" then
    set t to current track
    set out to out & us & (my stripFraming(name of t)) & us & ¬
      (my stripFraming(artist of t)) & us & (my stripFraming(album of t)) & us & ¬
      (persistent ID of t) & us & ((player position) as text) & us & ¬
      ((duration of t) as text)
  end if
end tell
end timeout
return out"""
)


def _parse_now_playing(raw: str) -> dict:
    fields = raw.split(US)
    state = fields[0].strip() if fields and fields[0].strip() else "stopped"
    if len(fields) < 7:  # stopped, or a transient state with no track payload
        return {"state": state}
    _, name, artist, album, pid, pos, dur = fields[:7]
    return {
        "state": state,
        "track": sanitize_line(name),
        "artist": sanitize_line(artist),
        "album": sanitize_line(album),
        "id": pid,
        "position": pos,
        "duration": dur,
    }
```

Add the method to `MusicAdapter` (after `get_pointers`):

```python
    def now_playing(self) -> dict:
        """Current player state + track, or {"state": "stopped"}."""
        return _parse_now_playing(run_osascript(_NOW_PLAYING))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_music.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint + format, then commit**

```bash
uv run ruff check macos_apps_mcp/adapters/music.py tests/test_music.py
uv run ruff format macos_apps_mcp/adapters/music.py tests/test_music.py
git add macos_apps_mcp/adapters/music.py tests/test_music.py
git commit -m "feat(music): #69 now_playing — player state + current track"
```

---

### Task 3: Actions — control / play_playlist / set_volume / set_mode

**Files:**
- Modify: `macos_apps_mcp/adapters/music.py`
- Test: `tests/test_music.py`

**Interfaces:**
- Consumes: `run_osascript`, `MusicAdapter.now_playing` (each action returns the resulting state).
- Produces (all validate args, then dispatch via argv, then return `self.now_playing()`):
  - `_ACTIONS: tuple[str, ...] = ("play", "pause", "playpause", "next", "previous")`
  - `_MODES: tuple[str, ...] = ("shuffle", "repeat")`
  - `_CONTROL`, `_PLAY_PLAYLIST`, `_SET_VOLUME`, `_SET_MODE` (AppleScript, argv)
  - `MusicAdapter().control(action: str) -> dict`
  - `MusicAdapter().play_playlist(ident: str) -> dict`
  - `MusicAdapter().set_volume(level: int) -> dict`
  - `MusicAdapter().set_mode(mode: str, on: bool) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_music.py`:

```python
def _recorder():
    """A fake run_osascript that records (script, args) and returns 'stopped' so the
    trailing now_playing() call parses to {"state": "stopped"}."""
    calls: list = []

    def fake(script, *args, **kwargs):
        calls.append((script, args))
        return "stopped"

    return calls, fake


def test_control_rejects_unknown_verb():
    with pytest.raises(ValueError):
        MusicAdapter().control("destroy")


def test_control_dispatches_action(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    assert MusicAdapter().control("next") == {"state": "stopped"}
    assert calls[0][0] is music._CONTROL
    assert calls[0][1] == ("next",)  # action via argv, never interpolated


def test_set_volume_rejects_out_of_range():
    with pytest.raises(ValueError):
        MusicAdapter().set_volume(150)


def test_set_volume_passes_level(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().set_volume(30)
    assert calls[0][0] is music._SET_VOLUME
    assert calls[0][1] == ("30",)


def test_set_mode_rejects_unknown_mode():
    with pytest.raises(ValueError):
        MusicAdapter().set_mode("crossfade", True)


def test_set_mode_maps_repeat_bool(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().set_mode("repeat", True)
    assert calls[0][1] == ("repeat", "1")


def test_play_playlist_requires_id():
    with pytest.raises(ValueError):
        MusicAdapter().play_playlist("  ")


def test_play_playlist_passes_id(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().play_playlist("PID1")
    assert calls[0][0] is music._PLAY_PLAYLIST
    assert calls[0][1] == ("PID1",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_music.py -k "control or volume or mode or playlist" -v`
Expected: FAIL — `AttributeError` (methods/templates not defined)

- [ ] **Step 3: Write the implementation**

In `macos_apps_mcp/adapters/music.py`, add near the top constants:

```python
_ACTIONS = ("play", "pause", "playpause", "next", "previous")
_MODES = ("shuffle", "repeat")
```

Add the templates after `_NOW_PLAYING` (all take argv; the Python side validates first,
so the argv string is always one of a fixed, safe set):

```python
_CONTROL = """on run argv
  set act to item 1 of argv
  with timeout of 120 seconds
  tell application "Music"
    if act is "play" then
      play
    else if act is "pause" then
      pause
    else if act is "playpause" then
      playpause
    else if act is "next" then
      next track
    else if act is "previous" then
      previous track
    end if
  end tell
  end timeout
end run"""

_PLAY_PLAYLIST = """on run argv
  set pid to item 1 of argv
  with timeout of 120 seconds
  tell application "Music"
    try
      set p to (first playlist whose persistent ID is pid)
    on error
      error "no playlist with id " & pid & "; call music_search for valid ids"
    end try
    play p
  end tell
  end timeout
end run"""

_SET_VOLUME = """on run argv
  set lvl to (item 1 of argv) as integer
  with timeout of 120 seconds
  tell application "Music"
    set sound volume to lvl
  end tell
  end timeout
end run"""

_SET_MODE = """on run argv
  set md to item 1 of argv
  set onFlag to (item 2 of argv) is "1"
  with timeout of 120 seconds
  tell application "Music"
    if md is "shuffle" then
      set shuffle enabled to onFlag
    else if md is "repeat" then
      if onFlag then
        set song repeat to all
      else
        set song repeat to off
      end if
    end if
  end tell
  end timeout
end run"""
```

Add the methods to `MusicAdapter`:

```python
    # ponytail: each action does one extra osascript round-trip (now_playing) to return
    # a useful resulting state. Fine — actions are interactive, not a hot loop. Return a
    # cheaper confirmation dict if that ever shows up as latency.
    def control(self, action: str) -> dict:
        """Playback control: action in play|pause|playpause|next|previous."""
        action = action.strip().lower()
        if action not in _ACTIONS:
            raise ValueError(
                f"unknown music action {action!r}; expected one of "
                f"{', '.join(_ACTIONS)}"
            )
        run_osascript(_CONTROL, action)
        return self.now_playing()

    def play_playlist(self, ident: str) -> dict:
        """Play a playlist by its persistent id (from music_search)."""
        ident = ident.strip()
        if not ident:
            raise ValueError(
                "play_playlist needs a playlist id (got empty); call music_search"
            )
        run_osascript(_PLAY_PLAYLIST, ident)
        return self.now_playing()

    def set_volume(self, level: int) -> dict:
        """Set the Music app sound volume (0–100)."""
        if not 0 <= level <= 100:
            raise ValueError(f"volume must be 0–100; got {level}")
        run_osascript(_SET_VOLUME, str(level))
        return self.now_playing()

    def set_mode(self, mode: str, on: bool) -> dict:
        """Set shuffle (boolean) or repeat (on→all, off→off)."""
        mode = mode.strip().lower()
        if mode not in _MODES:
            raise ValueError(
                f"unknown mode {mode!r}; expected one of {', '.join(_MODES)}"
            )
        run_osascript(_SET_MODE, mode, "1" if on else "0")
        return self.now_playing()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_music.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Lint + format, then commit**

```bash
uv run ruff check macos_apps_mcp/adapters/music.py tests/test_music.py
uv run ruff format macos_apps_mcp/adapters/music.py tests/test_music.py
git add macos_apps_mcp/adapters/music.py tests/test_music.py
git commit -m "feat(music): #69 playback actions — control/play_playlist/volume/mode"
```

---

### Task 4: Wire the 6 tools into `server.py` + doctor + annotation guard

**Files:**
- Modify: `macos_apps_mcp/server.py`
- Modify: `macos_apps_mcp/doctor.py:35`
- Modify: `tests/test_tool_annotations.py`

**Interfaces:**
- Consumes: `MusicAdapter` (Task 1–3), `_read_tool`, `_additive_tool` (server), `_AUTOMATION_APPS` (doctor).
- Produces registered tools: `music_search`, `now_playing`, `music_control`, `play_playlist`, `set_volume`, `set_mode`.

- [ ] **Step 1: Update the annotation guard test (failing first)**

In `tests/test_tool_annotations.py`, add the four additive tools to `_ADDITIVE_TOOLS`:

```python
_ADDITIVE_TOOLS = frozenset(
    {
        "create_reminder",
        "create_event",
        "create_contact",
        "safari_open",
        "create_draft",
        "mail_reply",
        "create_note",
        "music_control",
        "play_playlist",
        "set_volume",
        "set_mode",
    }
)
```

Add the six tools to `_PERMISSION` (all Automation):

```python
    "music_search": "Automation",
    "now_playing": "Automation",
    "music_control": "Automation",
    "play_playlist": "Automation",
    "set_volume": "Automation",
    "set_mode": "Automation",
```

Add the four actions to the `envelope_only` set in `test_every_write_tool_is_audit_classified`:

```python
    envelope_only = {
        "create_reminder",
        "create_event",
        "create_note",
        "create_contact",
        "create_draft",
        "mail_reply",
        "safari_open",
        "run_shortcut",
        "music_control",
        "play_playlist",
        "set_volume",
        "set_mode",
    }
```

- [ ] **Step 2: Run the annotation tests to verify they fail**

Run: `uv run pytest tests/test_tool_annotations.py -v`
Expected: FAIL — the map lists tools that aren't registered yet (`read tool(s) missing from registration` / `envelope_only` mismatch).

- [ ] **Step 3: Register the tools + probe Music in doctor**

In `macos_apps_mcp/server.py`, add the import next to the other adapter imports (near `from .adapters.safari import SafariAdapter`):

```python
from .adapters.music import MusicAdapter
```

Add the instance next to the other adapter instances (near `_safari = SafariAdapter()`):

```python
_music = MusicAdapter()
```

Add the read tools next to the other `@_read_tool` reads (e.g. after `safari_tabs`):

```python
@_read_tool
def music_search(query: str = "") -> list[dict[str, str]]:
    """Search the Music library + playlists as pointers. `query` optional
    name/artist/album substring (empty lists all, bounded). Read-only; needs Automation
    access for Music. Pointers only (id = persistent ID); no audio plays."""
    return [p.as_dict() for p in _music.get_pointers(query)]


@_read_tool
def now_playing() -> dict:
    """Current Music player state + track (name/artist/album/id/position/duration), or
    {"state": "stopped"}. Read-only; needs Automation access for Music."""
    return _music.now_playing()
```

Add the additive tools next to the other `@_additive_tool` writes (e.g. after `safari_open`):

```python
@_additive_tool
def music_control(action: str) -> dict:
    """Control Music playback: action in play|pause|playpause|next|previous. Additive,
    reversible player-state change; needs Automation access for Music. Returns the
    resulting now-playing state."""
    return _music.control(action)


@_additive_tool
def play_playlist(id: str) -> dict:
    """Play a Music playlist by its persistent id (from music_search). Additive,
    reversible; needs Automation access for Music. Returns the resulting now-playing
    state."""
    return _music.play_playlist(id)


@_additive_tool
def set_volume(level: int) -> dict:
    """Set the Music app sound volume (0–100). Additive, reversible; needs Automation
    access for Music. Returns the resulting now-playing state."""
    return _music.set_volume(level)


@_additive_tool
def set_mode(mode: str, on: bool) -> dict:
    """Set Music shuffle or repeat: mode in shuffle|repeat, on=true/false (repeat on→all,
    off→off). Additive, reversible; needs Automation access for Music. Returns the
    resulting now-playing state."""
    return _music.set_mode(mode, on)
```

In `macos_apps_mcp/doctor.py:35`, add `"Music"` to `_AUTOMATION_APPS`:

```python
_AUTOMATION_APPS = ("Mail", "Notes", "Contacts", "Photos", "Safari", "Messages", "Music")
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run pytest`
Expected: PASS — the annotation guard now matches the 6 registered tools; full suite green.

- [ ] **Step 5: Lint + format, then commit**

```bash
uv run ruff check .
uv run ruff format --check .
git add macos_apps_mcp/server.py macos_apps_mcp/doctor.py tests/test_tool_annotations.py
git commit -m "feat(music): #69 register 6 Music tools + doctor probe"
```

---

### Task 5: Integration playback tests (on-device only)

**Files:**
- Create: `tests/integration/test_music_integration.py`

**Interfaces:**
- Consumes: `MusicAdapter` (real osascript, real Music.app). Marked `@pytest.mark.integration` — runs only via `uv run pytest -m integration`, NEVER in CI.

- [ ] **Step 1: Confirm the integration marker exists**

Run: `grep -n "integration" pyproject.toml`
Expected: a `markers` entry registering `integration` (used by the other `tests/integration/` suites). If absent, register it under `[tool.pytest.ini_options] markers` — but the sibling suites already use it, so it should be present.

- [ ] **Step 2: Write the integration tests**

Create `tests/integration/test_music_integration.py`:

```python
"""Real Music.app playback tests (#69) — on-device only, NEVER CI.

Run manually: `uv run pytest -m integration -k music`. These are AUDIBLE (they start
playback); each test restores prior state (pause + restore volume) in teardown.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp.adapters.music import MusicAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
def adapter():
    return MusicAdapter()


def test_now_playing_shape(adapter):
    state = adapter.now_playing()
    assert "state" in state
    assert state["state"] in {
        "stopped", "playing", "paused", "fast forwarding", "rewinding",
    }


def test_play_pause_roundtrip(adapter):
    try:
        playing = adapter.control("play")
        assert playing["state"] in {"playing", "stopped"}  # stopped if library empty
        paused = adapter.control("pause")
        assert paused["state"] in {"paused", "stopped"}
    finally:
        adapter.control("pause")


def test_set_volume_restores(adapter):
    before = adapter.now_playing()  # (volume isn't in now_playing; capture via osascript)
    from macos_apps_mcp.runtime import run_osascript

    prior = int(run_osascript('tell application "Music" to get sound volume'))
    try:
        adapter.set_volume(40)
        after = int(run_osascript('tell application "Music" to get sound volume'))
        assert after == 40
    finally:
        adapter.set_volume(prior)
    assert before is not None


def test_set_mode_shuffle_toggles(adapter):
    from macos_apps_mcp.runtime import run_osascript

    prior = run_osascript('tell application "Music" to get shuffle enabled')
    try:
        adapter.set_mode("shuffle", True)
        on = run_osascript('tell application "Music" to get shuffle enabled')
        assert on == "true"
    finally:
        adapter.set_mode("shuffle", prior == "true")


def test_play_playlist_by_id(adapter):
    # discover a real playlist id via the read path, then play it
    ptrs = adapter.get_pointers("")
    playlists = [p for p in ptrs if " tracks)" in p.summary]
    if not playlists:
        pytest.skip("no user playlists on this Mac")
    try:
        state = adapter.play_playlist(playlists[0].id)
        assert "state" in state
    finally:
        adapter.control("pause")
```

- [ ] **Step 3: Run the integration tests on-device**

Run: `uv run pytest -m integration -k music -v`
Expected: PASS on this Mac (Music grants Automation; may prompt once). Tests are audible.

- [ ] **Step 4: Confirm they are excluded from the default run**

Run: `uv run pytest -k music -v`
Expected: the integration tests are DESELECTED (only `tests/test_music.py` unit tests run) — confirming `-m integration` gating.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_music_integration.py
git commit -m "test(music): #69 on-device playback integration tests"
```

---

## Whole-branch verification (before PR)

Run all three gates from a clean tree; report actual output, never suppress failures:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Then on-device once: `uv run pytest -m integration -k music`.

## Self-review notes (author)

- **Spec coverage:** tool surface (6 tools) → Tasks 1–4; Pointer contract + empty deeplink → Task 1; fold_text #26 fix → Task 1; now_playing stopped-guard → Task 2; additive classification + read-only stripping → Task 4 (`@_additive_tool`); id-addressed play_playlist → Task 3; volume/mode validation + repeat tri-state mapping → Task 3; doctor probe → Task 4; integration-marked tests → Task 5. All acceptance boxes covered.
- **Read-only-mode check:** the additive tools are registered via `@_additive_tool`, which returns the bare function under `MACOS_APPS_READ_ONLY` (unregistered) — the annotation test's `missing <= _WRITE_TOOLS` branch already tolerates that, so no extra work.
- **No new dependencies** (ponytail): pure osascript + existing text/runtime/contracts helpers.
