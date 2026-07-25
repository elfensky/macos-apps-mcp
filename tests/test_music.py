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


def _recorder():
    """A fake run_osascript that records (script, args) and returns 'stopped' so the
    trailing now_playing() call parses to {"state": "stopped"}."""
    calls: list = []

    def fake(script, *args, **kwargs):
        calls.append((script, args))
        return "stopped"

    return calls, fake


def test_control_rejects_unknown_verb():
    import pytest

    with pytest.raises(ValueError):
        MusicAdapter().control("destroy")


def test_control_dispatches_action(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    assert MusicAdapter().control("next") == {"state": "stopped"}
    assert calls[0][0] is music._CONTROL
    assert calls[0][1] == ("next",)  # action via argv, never interpolated


def test_set_volume_rejects_out_of_range():
    import pytest

    with pytest.raises(ValueError):
        MusicAdapter().set_volume(150)


def test_set_volume_passes_level(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().set_volume(30)
    assert calls[0][0] is music._SET_VOLUME
    assert calls[0][1] == ("30",)


def test_set_mode_rejects_unknown_mode():
    import pytest

    with pytest.raises(ValueError):
        MusicAdapter().set_mode("crossfade", True)


def test_set_mode_maps_repeat_bool(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().set_mode("repeat", True)
    assert calls[0][1] == ("repeat", "1")


def test_play_playlist_requires_id():
    import pytest

    with pytest.raises(ValueError):
        MusicAdapter().play_playlist("  ")


def test_play_playlist_passes_id(monkeypatch):
    calls, fake = _recorder()
    monkeypatch.setattr(music, "run_osascript", fake)
    MusicAdapter().play_playlist("PID1")
    assert calls[0][0] is music._PLAY_PLAYLIST
    assert calls[0][1] == ("PID1",)
