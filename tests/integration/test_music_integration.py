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
        "stopped",
        "playing",
        "paused",
        "fast forwarding",
        "rewinding",
    }
    # position/duration must be locale-proof integer-second strings — a bare AppleScript
    # `(real as text)` renders a comma decimal on non-en_US Macs (e.g. "195,022"), which
    # is un-parseable. Only a live run catches this, so guard it here.
    if state["state"] != "stopped":
        assert state["position"].isdigit(), state["position"]
        assert state["duration"].isdigit(), state["duration"]


def test_play_pause_roundtrip(adapter):
    try:
        playing = adapter.control("play")
        # stopped if the library is empty; paused observed on device 2026-08-23 when
        # `play` hits a cold-launched Music with nothing queued — the verb is
        # accepted, the player just has nothing to advance into.
        assert playing["state"] in {"playing", "paused", "stopped"}
        paused = adapter.control("pause")
        assert paused["state"] in {"paused", "stopped"}
    finally:
        adapter.control("pause")


def test_set_volume_restores(adapter):
    # volume isn't in now_playing; capture via osascript
    before = adapter.now_playing()
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
