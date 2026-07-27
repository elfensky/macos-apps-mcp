"""Suite-wide hermeticity guard (#141).

deploy.allow_send_file() (and anything else routed through audit.state_dir())
resolves ``$XDG_STATE_HOME/macos-apps-mcp`` per call. Without this fixture that
falls back to the developer's real ``~/.local/state/macos-apps-mcp`` — so a test
run could read/write Andrei's live outbound-send toggle. Session-scoped so it
applies before any test (including collection-time fixtures) ever touches state
dir; ``pytest.MonkeyPatch`` (not the function-scoped ``monkeypatch`` fixture,
which can't be used at session scope) makes the env change and undoes it once
per session.
"""

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_xdg_state_home(tmp_path_factory):
    state_home = tmp_path_factory.mktemp("xdg-state-home")
    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", str(state_home))
    yield state_home
    mp.undo()
