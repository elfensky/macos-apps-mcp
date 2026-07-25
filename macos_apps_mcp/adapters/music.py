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
    STRIP_FRAMING,
    US,
    clean_summary,
    fold_text,
    sanitize_line,
    split_framed,
)

MAX_MUSIC_RESULTS = 50  # pointers-not-payload: cap tracks + playlists combined

_ACTIONS = ("play", "pause", "playpause", "next", "previous")
_MODES = ("shuffle", "repeat")

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


def _track_pointer(name: str, artist: str, album: str, pid: str) -> Pointer:
    summary = name
    if artist:
        summary = f"{name} — {artist}"
    if album:
        summary = f"{summary} ({album})"
    return Pointer(id=pid, summary=clean_summary(summary), deeplink="")


def _playlist_pointer(name: str, count: str, pid: str) -> Pointer:
    return Pointer(
        id=pid, summary=clean_summary(f"{name} ({count} tracks)"), deeplink=""
    )


def _parse_search(raw: str) -> list[tuple[Pointer, str]]:
    """Parse the framed search payload into (Pointer, fold-key) pairs. The fold-key is
    the searchable text folded (#64) so the Python-side filter is diacritic/smart-punct
    insensitive on BOTH sides — the #26 fix. Malformed/short records are skipped."""
    out: list[tuple[Pointer, str]] = []
    for rec in split_framed(raw):
        if rec[0] == "T" and len(rec) >= 5:
            _, name, artist, album, pid = rec[:5]
            out.append(
                (
                    _track_pointer(name, artist, album, pid),
                    fold_text(f"{name} {artist} {album}"),
                )
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

    def now_playing(self) -> dict:
        """Current player state + track, or {"state": "stopped"}."""
        return _parse_now_playing(run_osascript(_NOW_PLAYING))

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
