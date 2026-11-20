"""Suite-wide hermeticity guard (#141).

Two separate leaks, isolated two different ways — the difference matters:

* ``audit.state_dir()`` (audit log, the FTS body sidecar) resolves
  ``$XDG_STATE_HOME/macos-apps-mcp`` per call, so pointing that env var at a tmp dir
  moves everything routed through it off the developer's real state dir.
* ``deploy._ALLOW_SEND_FILE``, ``deploy._ADAPTERS_OFF_FILE`` and
  ``deploy._DASHBOARD_KEY_FILE`` are home-anchored ON
  PURPOSE and must stay that way (the
  launchd daemon, the shell that writes the toggle and a client-spawned shim have to
  agree on one path — see the comment on the constant). So they are isolated by
  monkeypatching the constants themselves, NOT by moving XDG_STATE_HOME. Without this
  a test run could read/write Andrei's live outbound-send toggle or adapter deny-list
  (D-17). ``deploy._CLI_LINK`` and ``deploy._SETUP_PENDING_FILE`` are home paths
  too, patched the same way so no test touches the real ``~/.local``.
* The daemon socket moves through its own override, ``MACOS_APPS_MCP_SOCKET``: a test
  that reaches ``uninstall_agent()`` unlinks ``socket_path()``, and the live daemon's
  socket once went with it (clients could no longer connect until a restart). The
  default folder behind that override, ``daemon._DEFAULT_SOCKET_DIR``, is patched too:
  ``socket_path()`` creates it when a test removes the override.

Session-scoped so both apply before any test (including collection-time fixtures)
touches either; ``pytest.MonkeyPatch`` (not the function-scoped ``monkeypatch``
fixture, which can't be used at session scope) makes the changes and undoes them once
per session.

* The app stores (Notes, Messages, Reminders, the Photos prefs, the Mail index and the
  Mail folder) and the default file root are locked by the function-scoped
  ``_no_real_stores`` (#581). It is function-scoped because an integration test must
  read the real stores, and a session-scoped patch cannot read a test's marks.
"""

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from macos_apps_mcp import daemon, deploy, doctor, eventkit, runtime
from macos_apps_mcp.adapters import (
    mail_addressing,
    mail_ids,
    mail_index,
    mail_reply_cleanup,
    messages,
    notes,
    reminders_store,
)
from macos_apps_mcp.errors import NativeError
from tests.envelope import SCHEMA, Envelope, seed_base

# The home-anchored store paths (#581): module, name, and the absent path under the
# session's temp folder that a unit test gets instead.
_STORE_PATHS = (
    (notes, "NOTESTORE", "absent-notes/NoteStore.sqlite"),
    (messages, "CHAT_DB", "absent-messages/chat.db"),
    (reminders_store, "_STORES", "absent-reminders/Stores"),
    (runtime, "_PHOTOS_PREFS", "absent-photos/com.apple.Photos.plist"),
)
# These two read ``Path.home()`` at call time, so they have no constant to move.
_STORE_FUNCTIONS = ("envelope_index_path", "mail_root")
# The real objects, read before any patch: the lock replaces each one, and its copies.
REAL_STORE_OBJECTS = {name: getattr(mod, name) for mod, name, _ in _STORE_PATHS} | {
    name: getattr(mail_index, name) for name in _STORE_FUNCTIONS
}

# The real default folder of the daemon socket, read before ``_isolated_state`` moves
# it.
REAL_DEFAULT_SOCKET_DIR = daemon._DEFAULT_SOCKET_DIR

# The areas of the real home that no unit test may read or change.
_HOME_AREAS = (
    "Library/Mail",
    "Library/Messages",
    "Library/Group Containers",
    "Library/Containers/com.apple.Photos",
    "Library/Application Support/com.apple.TCC",
    "Downloads",
    ".local/state/macos-apps-mcp",
)
_SYSTEM_AREAS = ("/Library/Application Support/com.apple.TCC",)
# Each audit event that carries a path -> how many of its first arguments are paths.
# Reads first, then the events that write or delete (a test once unlinked the live
# daemon's socket). Every name was seen on Python 3.14 with a probe in a temp folder.
_STORE_EVENTS = {
    "open": 1,
    "sqlite3.connect": 1,
    "os.scandir": 1,
    "os.listdir": 1,
    "os.remove": 1,
    "os.rename": 2,
    "os.mkdir": 1,
    "os.rmdir": 1,
    "os.truncate": 1,
    "os.chmod": 1,
    "os.chown": 1,
    "os.utime": 1,
    "os.symlink": 2,
    "os.link": 2,
    "shutil.rmtree": 1,
    "shutil.move": 2,
    "shutil.copyfile": 2,
    "shutil.copytree": 2,
}
_STORE_REFUSAL = (
    "a unit test reached a real app store ({what}) — give the test a fixture store "
    "or a fake (fake_envelope, blank_envelope, tests/_fakes.py); see _no_real_stores"
)
_DATA_VOLUME = "/system/volumes/data"
# The reads that the running unit test tried; None outside a unit test (hook off).
_store_hits: list[str] | None = None
# Set on a test whose own body failed with the refusal (see pytest_runtest_makereport).
_REFUSED = pytest.StashKey[bool]()


class RealStoreReached(AssertionError):
    """A unit test tried to read or change a real app store."""


def _normal(path: str) -> str:
    """One spelling of a path for the compare: absolute, without ``..``, with each
    symlink resolved, case-folded (APFS ignores case) and without the Data-volume
    alias. ``realpath`` was chosen over ``abspath``: only it follows a symlink. It
    stats the path and reads a link; it reads no file content."""
    path = os.path.realpath(path).casefold()
    return (
        path.removeprefix(_DATA_VOLUME) if path.startswith(_DATA_VOLUME + "/") else path
    )


def _store_areas(home: Path, checkout: str) -> dict[str, str]:
    """``{normal path: shown name}`` of the watched areas under ``home``.

    The shown name uses ``~`` for the home and is fixed here, so a refusal never prints
    the home path, also when a test changed ``HOME``. An area that holds this checkout
    is left out, or every read of the repo would be refused."""
    areas = {_normal(str(home / part)): f"~/{part}" for part in _HOME_AREAS}
    areas |= {_normal(area): area for area in _SYSTEM_AREAS}
    here = _normal(checkout)
    return {a: shown for a, shown in areas.items() if not here.startswith(a + "/")}


_REAL_STORE_AREAS = _store_areas(Path.home(), __file__)


def _event_path(event: str, target) -> str | None:
    """The normal path of one event argument, or None when it names no path."""
    if isinstance(target, os.PathLike):
        target = os.fspath(target)
    if isinstance(target, bytes):
        target = os.fsdecode(target)
    if not isinstance(target, str):
        return None  # a file descriptor
    if event == "sqlite3.connect" and target.startswith("file:"):
        # a URI in any authority form: file:/p, file:///p, file://localhost/p, file:p
        target = unquote(urlsplit(target).path)
    try:
        return _normal(target)
    except (OSError, ValueError):  # no current folder, or a NUL: the call fails anyway
        return None


def _refuse_real_store(event: str, args: tuple) -> None:
    """The audit hook of ``_no_real_stores``: refuse a read or a change under a real
    store area. It runs BEFORE the system call, so the read or the change does not
    happen. The limits are listed in the docstring of ``_no_real_stores``."""
    paths = _STORE_EVENTS.get(event)
    if paths is None or _store_hits is None:
        return
    for target in args[:paths]:
        path = _event_path(event, target)
        if path is None:
            continue
        for area, shown in _REAL_STORE_AREAS.items():
            # the separator: ~/Library/Mailboxes is not under ~/Library/Mail
            if path == area or path.startswith(area + "/"):
                what = f"{event} under {shown}"  # the area only: no file name
                _store_hits.append(what)
                raise RealStoreReached(_STORE_REFUSAL.format(what=what))


sys.addaudithook(_refuse_real_store)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Mark a test whose own body failed with the refusal. The teardown of
    ``_no_real_stores`` is then silent: one refused read is one FAILED line, not a
    FAILED line and an ERROR line."""
    report = yield
    refused = call.excinfo is not None and call.excinfo.errisinstance(RealStoreReached)
    if call.when == "call" and refused:
        item.stash[_REFUSED] = True
    return report


def _is_integration(node) -> bool:
    """True for a test that carries the ``integration`` marker. ``request.keywords``
    is not the test: it also holds parametrize ids, function attributes and the names
    of the folders above the test."""
    return node.get_closest_marker("integration") is not None


@pytest.fixture(autouse=True, scope="session")
def _isolated_state(tmp_path_factory):
    state_home = tmp_path_factory.mktemp("xdg-state-home")
    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", str(state_home))
    mp.setenv("MACOS_APPS_MCP_SOCKET", str(state_home / "daemon" / "mcp.sock"))
    mp.setattr(deploy, "_ALLOW_SEND_FILE", state_home / "allow_send")
    mp.setattr(deploy, "_ADAPTERS_OFF_FILE", state_home / "adapters_off")
    mp.setattr(deploy, "_DASHBOARD_KEY_FILE", state_home / "daemon" / "dashboard_key")
    mp.setattr(deploy, "_CLI_LINK", state_home / "bin" / "macos-apps-mcp")
    mp.setattr(deploy, "_SETUP_PENDING_FILE", state_home / "setup_pending")
    # socket_path() creates this folder when the override above is removed
    mp.setattr(daemon, "_DEFAULT_SOCKET_DIR", state_home / "default-daemon")
    tcc_user = state_home / "absent-tcc-user" / "TCC.db"
    tcc_system = state_home / "absent-tcc-system" / "TCC.db"
    mp.setattr(deploy, "_TCC_DB", tcc_user)
    mp.setattr(deploy, "_TCC_SYSTEM_DB", tcc_system)
    # a tuple frozen at import, so it needs its own patch beside the two constants
    mp.setattr(doctor, "_FDA_PATHS", (tcc_user, tcc_system))
    yield state_home
    mp.undo()


@pytest.fixture(autouse=True)
def _reset_account_map_globals(monkeypatch):
    """Reset mail_addressing's account-map cache globals before every test.

    _ACCOUNT_MAP_CACHE, _ACCOUNT_MAP_FAILURE_AT and _ACCOUNT_MAP_REFRESHED_AT (the #359
    re-read stamp) are the parts of ONE cache — the failure timestamp is what lets
    account_map() reap a stale failure and retry. They must be reset TOGETHER, in one
    place: resetting only the cache dict leaves a live monotonic timestamp behind, and
    once real (or monkeypatched) time crosses _ACCOUNT_MAP_FAILURE_TTL past it,
    account_map() silently wipes a cache dict a LATER test installed for its own
    purposes and falls through to the real run_osascript — spawning osascript against
    Mail.app from a unit test. This is set BEFORE each test (not just torn down after)
    so a leak written by plain global assignment in production code — which monkeypatch
    can't see coming — never survives into the next test either. If another global
    joins this cache, it must be added here too, or it becomes the next leak of this
    exact class.
    """
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_CACHE", None)
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_FAILURE_AT", None)
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_REFRESHED_AT", None)


@pytest.fixture(autouse=True)
def _reset_mail_index_mode_globals(monkeypatch):
    """Reset mail_index's #201 store-mode cache before every test — the same leak
    class (and the same fix) as the account-map cache above: a mode cached while
    one test's monkeypatched sidecar existed must never leak into the next test's
    assertions. (Staleness deliberately holds no module state to reset — the
    global-note design was a cross-read leak in production too, caught by the rig
    e2e and replaced by the per-call ``staleness_note()``.)"""
    monkeypatch.setattr(mail_index, "_MODE_CACHE", {})


def sequoiaify_envelope(db: Path, side: Path) -> None:
    """Reshape a test-built (native/Tahoe-shaped) Envelope Index into the SEQUOIA
    shape — ``message_global_data`` keeps its rows and its ``message_id`` column but
    loses ``message_id_header`` — and build the sidecar a real ``mail_index_ids``
    harvest would have produced from it (mapping + high-water mark). Idempotent:
    a store already reshaped (or one a test built deliberately broken) is left
    alone. The #201 battery's whole point is that production code then serves the
    SAME queries through mode detection + ATTACH + shadow view, unmodified.

    Carries ``message_id`` across the reshape when the source table has it
    (GATE-08): the earlier version copied only ``ROWID``, which silently NULLed
    out ``message_id`` for every row — the exact column
    ``build_sent_triage_query`` joins on (``g.message_id = m.message_id``), so a
    reshaped store answered the sent-triage query with zero rows in sidecar mode
    even though the same query worked fine in native mode."""
    conn = sqlite3.connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(message_global_data)")}
        if "message_id_header" not in cols:
            return
        has_message_id = "message_id" in cols
        extra = ", message_id" if has_message_id else ""
        rows = conn.execute(
            f"SELECT ROWID, message_id_header{extra} FROM message_global_data"
            " WHERE message_id_header IS NOT NULL AND message_id_header <> ''"
        ).fetchall()
        (max_rowid,) = conn.execute(
            "SELECT COALESCE(MAX(ROWID), 0) FROM messages"
        ).fetchone()
        copy_cols = "ROWID" + (", message_id" if has_message_id else "")
        conn.executescript(
            "ALTER TABLE message_global_data RENAME TO mgd_native;"
            "CREATE TABLE message_global_data("
            "ROWID INTEGER PRIMARY KEY, message_id INTEGER);"
            f"INSERT INTO message_global_data({copy_cols})"
            f" SELECT {copy_cols} FROM mgd_native;"
            "DROP TABLE mgd_native;"
        )
        conn.commit()
    finally:
        conn.close()
    sc = mail_ids._connect(side)  # the real schema, one source of truth
    try:
        # global_ids is (global_message_id, message_id_header) only — rows may carry
        # a third (message_id) column when the source had one; keep just the two
        # the sidecar schema declares.
        sc.executemany(
            "INSERT OR REPLACE INTO global_ids VALUES (?, ?)",
            [(r[0], r[1]) for r in rows],
        )
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


@pytest.fixture
def fake_envelope(tmp_path, monkeypatch, envelope_mode):
    """The shared Envelope Index fixture (GATE-08, #180): seeds
    ``tmp_path / "Envelope Index"`` with ``seed_base``, points
    ``mail_index.envelope_index_path`` at it, and returns an ``Envelope`` handle for
    tests that need a few more rows on top of the canonical set.

    Depends on ``envelope_mode``, so EVERY consumer of this fixture runs twice —
    once native, once reshaped into the Sequoia shape with a Message-ID sidecar —
    with no per-test opt-in required. Leaves ``mail_root`` untouched: the on-disk
    ``.emlx`` plane is each test's own seam, this fixture only owns the sqlite
    store."""
    db = tmp_path / "Envelope Index"
    seed_base(db)
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    return Envelope(db)


@pytest.fixture
def blank_envelope(tmp_path, monkeypatch, envelope_mode):
    """Like ``fake_envelope``, but a SCHEMA-only store with no ``seed_base`` rows —
    for a test that needs exact control over row counts (an arithmetic assertion,
    or a specific url list) that layering onto the canonical seed would shift.
    Still parametrized over ``envelope_mode``, so these queries get real
    native+sidecar coverage too. The file sits where Mail keeps it
    (``<mail root>/V10/MailData/Envelope Index``), so the ``V10`` folder beside it is
    the tree of the ``.emlx`` files this index describes."""
    db = tmp_path / "V10" / "MailData" / "Envelope Index"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    return Envelope(db)


@pytest.fixture(autouse=True)
def _no_real_osascript(request, monkeypatch):
    """Fail CLOSED on the native seam: a unit test that forgets to fake it raises
    instead of spawning osascript, writing a real tempfile, or running a real
    subprocess against a live app (#176, GATE-01).

    Covers every seam name — ``run_osascript``, ``body_file``, ``tracked_run``,
    ``photos_db``, ``automation_permission``, ``accessibility_trusted``,
    ``compose_insert`` (the last two drive AX, CoreGraphics and the general pasteboard
    for the Mail reply flow, #348) — and only reaches code that calls each
    one qualified (``runtime.<seam>``); adapters still holding a module-global copy are
    unaffected. A test's own
    ``monkeypatch.setattr(runtime, <seam>, ...)`` simply overrides this fixture (last
    write wins), and a seam's own self-tests bind the real function at test-module
    import time instead (the ``tests/test_runtime.py`` convention for
    ``run_osascript``/``body_file``). Integration tests (``-m integration``) must
    reach real apps, so they are exempt.
    """
    if _is_integration(request.node):
        return

    for seam in (
        "run_osascript",
        "body_file",
        "tracked_run",
        "photos_db",
        "automation_permission",
        "accessibility_trusted",
        "compose_insert",
    ):

        def _refuse(*_args, _seam=seam, **_kwargs):
            raise AssertionError(
                f"a unit test reached {_seam} — fake it with "
                f"monkeypatch.setattr(runtime, '{_seam}', ...)"
            )

        monkeypatch.setattr(runtime, seam, _refuse)

    # eventkit.store() creates the process's real EKEventStore (#581). The Calendar
    # and Reminders adapters hold by-name copies (``from ..eventkit import store``),
    # so refuse every module attribute that IS the real function, not only the source.
    def _no_store(*_args, **_kwargs):
        raise AssertionError(
            "a unit test reached eventkit.store (a real EKEventStore) — fake it with "
            "monkeypatch.setattr(<module>, 'store', lambda: <fake store>)"
        )

    # Package modules only: a test module's own by-name import stays real, the
    # convention the runtime seams use for their self-tests.
    real_store = eventkit.store
    for name, mod in list(sys.modules.items()):
        if name.startswith("macos_apps_mcp") and getattr(mod, "store", 0) is real_store:
            monkeypatch.setattr(mod, "store", _no_store)

    # The index read of the reply sweep (#348) reads the user's real Envelope Index
    # unless a test supplies its own rows: refuse like an unreadable index, which the
    # flow tolerates (no sweep) instead of failing a test that never asked for one.
    def _no_index(*_args, **_kwargs):
        raise NativeError("the Envelope Index is not readable in a unit test")

    monkeypatch.setattr(mail_reply_cleanup, "_read", _no_index)

    # A pure formatter, not a native door to refuse: a deterministic stand-in so a
    # quote test needs no Foundation (tests/test_runtime.py binds the real one).
    monkeypatch.setattr(
        runtime,
        "mail_attribution_stamp",
        lambda when: (f"{when.day} {when:%b} {when.year}", f"{when:%H:%M}"),
    )


@pytest.fixture(autouse=True)
def _no_real_stores(request, monkeypatch, _isolated_state):
    """Keep a unit test off the real app stores of the Mac (#581).

    Two parts. The paths: ``notes.NOTESTORE``, ``messages.CHAT_DB``,
    ``reminders_store._STORES`` and ``runtime._PHOTOS_PREFS`` point at absent paths
    under the session's temp folder, ``mail_index.envelope_index_path`` and
    ``mail_index.mail_root`` return ``None`` (the answer of a Mac with no Mail data),
    and ``MACOS_APPS_FILE_ROOT`` is a temp folder. A copy in another package module
    (``from … import NAME``) is replaced too. The refusal: a read or a change under a
    real store area (``_STORE_EVENTS``: open, sqlite connect, listing, remove, rename,
    mkdir and more) fails the test with the lock's message, also when the code under
    test caught it. So a test that reaches a real store by another route (a new
    home-anchored path, the real function bound by name) fails instead of touching the
    owner's data. The lock never returns a real path.

    The refusal compares normal paths, so a relative path, ``..``, another letter
    case, the ``/System/Volumes/Data`` alias, a symlink and a ``file:`` URI are seen.
    It does NOT see: a bare ``stat`` (no audit event), a child process, a sqlite
    ``ATTACH DATABASE`` (its event has no path), a path relative to a ``dir_fd``, and
    a fixture of wider scope that runs before this one.

    A test that needs a store builds its own (``fake_envelope``, ``blank_envelope``, a
    temp NoteStore) and patches the name: the lock runs first, so that patch wins.

    Function-scoped, not a part of the session-scoped ``_isolated_state``, because an
    integration test must read the real stores and only a function-scoped fixture can
    read a test's marks. Exempt: tests that carry the ``integration`` marker only.
    Tests marked ``device`` stay under the lock; that has no effect today, because the
    device suite reaches the Mac through the daemon's socket.

    The outside check is the audit plugin ``store_touch_audit.py`` of Phase 05.12
    (``pytest -p store_touch_audit``): 0 rows on the default suite. Yields the list of
    the refused events; the self-tests in ``tests/test_native_seam.py`` read it.
    """
    yield from _store_lock(request.node, monkeypatch, _isolated_state)


def _store_lock(node, monkeypatch, state_home):
    """The body of ``_no_real_stores``, a plain generator so that its self-tests can
    run the exemption and the teardown by hand."""
    global _store_hits
    if _is_integration(node):
        yield None
        return

    replacement = {name: state_home / rel for _, name, rel in _STORE_PATHS}
    replacement |= dict.fromkeys(_STORE_FUNCTIONS, lambda: None)
    # Package modules only, as for ``eventkit.store`` above.
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("macos_apps_mcp"):
            for name, real in REAL_STORE_OBJECTS.items():
                if getattr(mod, name, None) is real:
                    monkeypatch.setattr(mod, name, replacement[name])
    monkeypatch.setenv("MACOS_APPS_FILE_ROOT", str(state_home / "file-root"))

    hits: list[str] = []
    previous, _store_hits = _store_hits, hits
    try:
        yield hits
    finally:
        _store_hits = previous
    # The code under test may catch the refusal (``except Exception``): fail the test
    # here, with the same message, unless its own body already failed with it.
    if hits and not node.stash.get(_REFUSED, False):
        raise RealStoreReached(_STORE_REFUSAL.format(what=", ".join(sorted(set(hits)))))
