"""Suite-wide hermeticity guard (#141).

Two separate leaks, isolated two different ways — the difference matters:

* ``audit.state_dir()`` (audit log, the FTS body sidecar) resolves
  ``$XDG_STATE_HOME/macos-apps-mcp`` per call, so pointing that env var at a tmp dir
  moves everything routed through it off the developer's real state dir.
* ``deploy._ALLOW_SEND_FILE`` is home-anchored ON PURPOSE and must stay that way (the
  launchd daemon, the shell that writes the toggle and a client-spawned shim have to
  agree on one path — see the comment on the constant). So it is isolated by
  monkeypatching the constant itself, NOT by moving XDG_STATE_HOME. Without this a
  test run could read/write Andrei's live outbound-send toggle.

Session-scoped so both apply before any test (including collection-time fixtures)
touches either; ``pytest.MonkeyPatch`` (not the function-scoped ``monkeypatch``
fixture, which can't be used at session scope) makes the changes and undoes them once
per session.
"""

import pytest

from macos_apps_mcp import deploy
from macos_apps_mcp.adapters import mail_addressing


@pytest.fixture(autouse=True, scope="session")
def _isolated_state(tmp_path_factory):
    state_home = tmp_path_factory.mktemp("xdg-state-home")
    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", str(state_home))
    mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")
    yield state_home
    mp.undo()


@pytest.fixture(autouse=True)
def _reset_account_map_globals(monkeypatch):
    """Reset mail_addressing's account-map cache globals before every test.

    _ACCOUNT_MAP_CACHE and _ACCOUNT_MAP_FAILURE_AT are two halves of ONE cache — the
    failure timestamp is what lets account_map() reap a stale failure and retry. They
    must be reset TOGETHER, in one place: resetting only the cache dict leaves a live
    monotonic timestamp behind, and once real (or monkeypatched) time crosses
    _ACCOUNT_MAP_FAILURE_TTL past it, account_map() silently wipes a cache dict a
    LATER test installed for its own purposes and falls through to the real
    run_osascript — spawning osascript against Mail.app from a unit test. This is set
    BEFORE each test (not just torn down after) so a leak written by plain global
    assignment in production code — which monkeypatch can't see coming — never
    survives into the next test either. If a third global joins this cache, it must be
    added here too, or it becomes the next leak of this exact class.
    """
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_FAILURE_AT", None)
