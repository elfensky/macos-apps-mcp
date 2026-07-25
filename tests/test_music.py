"""Unit tests for the Music adapter — mock at the osascript boundary."""

from __future__ import annotations

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
    raw = _rec("T", "Don't Stop", "Band", "Alb", "TID1") + RS
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
