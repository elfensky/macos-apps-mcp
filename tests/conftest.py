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


@pytest.fixture(autouse=True, scope="session")
def _isolated_state(tmp_path_factory):
    state_home = tmp_path_factory.mktemp("xdg-state-home")
    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", str(state_home))
    mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")
    yield state_home
    mp.undo()
