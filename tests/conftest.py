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

import sqlite3
from pathlib import Path

import pytest

from macos_apps_mcp import deploy, runtime
from macos_apps_mcp.adapters import mail_addressing, mail_ids, mail_index


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


@pytest.fixture(autouse=True)
def _reset_mail_index_mode_globals(monkeypatch):
    """Reset mail_index's #201 store-mode globals before every test — the same leak
    class (and the same fix) as the account-map cache above: a mode cached while one
    test's monkeypatched sidecar existed, or a staleness note a test's read left
    unpopped, must never leak into the next test's assertions."""
    monkeypatch.setattr(mail_index, "_MODE_CACHE", {})
    monkeypatch.setattr(mail_index, "_STALENESS_NOTE", None)


def sequoiaify_envelope(db: Path, side: Path) -> None:
    """Reshape a test-built (native/Tahoe-shaped) Envelope Index into the SEQUOIA
    shape — ``message_global_data`` keeps its rows and its ``message_id`` column but
    loses ``message_id_header`` — and build the sidecar a real ``mail_index_ids``
    harvest would have produced from it (mapping + high-water mark). Idempotent:
    a store already reshaped (or one a test built deliberately broken) is left
    alone. The #201 battery's whole point is that production code then serves the
    SAME queries through mode detection + ATTACH + shadow view, unmodified."""
    conn = sqlite3.connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(message_global_data)")}
        if "message_id_header" not in cols:
            return
        rows = conn.execute(
            "SELECT ROWID, message_id_header FROM message_global_data"
            " WHERE message_id_header IS NOT NULL AND message_id_header <> ''"
        ).fetchall()
        (max_rowid,) = conn.execute(
            "SELECT COALESCE(MAX(ROWID), 0) FROM messages"
        ).fetchone()
        conn.executescript(
            "ALTER TABLE message_global_data RENAME TO mgd_native;"
            "CREATE TABLE message_global_data("
            "ROWID INTEGER PRIMARY KEY, message_id INTEGER);"
            "INSERT INTO message_global_data(ROWID) SELECT ROWID FROM mgd_native;"
            "DROP TABLE mgd_native;"
        )
        conn.commit()
    finally:
        conn.close()
    sc = mail_ids._connect(side)  # the real schema, one source of truth
    try:
        sc.executemany("INSERT OR REPLACE INTO global_ids VALUES (?, ?)", rows)
        sc.execute(
            "INSERT OR REPLACE INTO meta VALUES ('max_rowid_harvested', ?)",
            (str(max_rowid),),
        )
        sc.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', 'test')")
        sc.commit()
    finally:
        sc.close()


@pytest.fixture(params=["native", "sidecar"])
def envelope_mode(request, monkeypatch, tmp_path):
    """Run a fake-envelope test in BOTH store modes (#201) — the structural proof
    the sidecar is one code path, not two.

    ``native``: the store the test builds (it carries message_id_header) is served
    as-is. ``sidecar``: the store is reshaped at first open into the Sequoia shape
    plus a sidecar file, and the REAL production path — mode detection, the
    read-only ATTACH, the shadow TEMP VIEW — serves the identical assertions. The
    reshape hooks ``runtime._open_sqlite_ro`` (the seam the #201 spike used) so it
    runs AFTER the test finished building its fixture, whatever helpers it used."""
    if request.param == "native":
        return "native"
    side = tmp_path / "mail_ids_sidecar.sqlite"
    monkeypatch.setattr(mail_ids, "sidecar_path", lambda: side)
    monkeypatch.setattr(
        mail_index.platform, "mac_ver", lambda: ("15.7.9", ("", "", ""), "x86_64")
    )
    orig = runtime._open_sqlite_ro

    def wrapped(path, *, immutable=False):
        p = Path(path)
        if p.name == "Envelope Index" and Path.home() not in p.parents:
            sequoiaify_envelope(p, side)
        return orig(path, immutable=immutable)

    monkeypatch.setattr(runtime, "_open_sqlite_ro", wrapped)
    return "sidecar"


@pytest.fixture(autouse=True)
def _no_real_osascript(request, monkeypatch):
    """Fail CLOSED on the native seam: a unit test that forgets to fake it raises
    instead of spawning osascript against real Mail (#176).

    Only reaches code that calls the seam qualified — ``runtime.run_osascript`` — which
    since #176 is the whole mail plane; adapters still holding a module-global copy are
    unaffected, and a test that patches ``runtime`` itself simply overrides this.
    Integration tests (``-m integration``) must reach real apps, so they are exempt.
    """
    if "integration" in request.keywords:
        return

    def _refuse(*_args, **_kwargs):
        raise AssertionError(
            "a unit test reached run_osascript — fake it with "
            "monkeypatch.setattr(runtime, 'run_osascript', ...)"
        )

    monkeypatch.setattr(runtime, "run_osascript", _refuse)
