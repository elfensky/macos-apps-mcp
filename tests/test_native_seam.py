"""#176/GATE-01: every adapter + doctor reach the native seam QUALIFIED —
``runtime.run_osascript`` / ``runtime.body_file`` / ``runtime.tracked_run``.

``from ..runtime import run_osascript`` (etc.) lands a *copy* of the seam in the
importing module's namespace, so a test has to fake it once per module — and a
forgotten module fails OPEN: the call spawns osascript against real Mail (that is
#160, where a send tool did exactly that) or a real ``tracked_run`` subprocess.
Qualified calls mean one patch point, ``runtime``, however many modules the codebase
splits into. The runtime half of the lock — a unit test that forgets to fake a seam
raises instead of reaching a live app — lives in ``tests/conftest.py``'s autouse
``_no_real_osascript`` fixture; the self-tests below prove it fires.

Every ``adapters/*.py`` (except ``__init__.py``) plus ``doctor.py`` is covered, so a
NEW module inherits the rule without anyone remembering to add it here (card 1).

The AST tests also forbid a direct ``subprocess`` spawn (``run``/``Popen``/``call``/
``check_call``/``check_output``) in these modules — the only door to a subprocess is
``runtime.tracked_run`` (GATE-11).
"""

from __future__ import annotations

import ast
import contextlib
import os
import pathlib
import shutil
import sqlite3
import sys
import types

import pytest

from macos_apps_mcp import files, runtime
from macos_apps_mcp.adapters import mail_index, messages, notes, reminders_store
from tests import conftest

_SEAM = frozenset(
    {
        "run_osascript",
        "body_file",
        "tracked_run",
        "photos_db",
        "automation_permission",
        "accessibility_trusted",
        "compose_insert",
    }
)
_SPAWNERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
_ADAPTERS_DIR = pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters"
_NATIVE_MODULES = sorted(
    [p for p in _ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py"]
    + [_ADAPTERS_DIR.parent / "doctor.py"]
)


@pytest.mark.parametrize("path", _NATIVE_MODULES, ids=lambda p: p.name)
def test_native_module_does_not_import_the_seam_by_name(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("runtime"):
            offenders = _SEAM.intersection(a.name for a in node.names)
            assert not offenders, (
                f"{path.name}:{node.lineno} imports {sorted(offenders)} by name — "
                "use `from .. import runtime` and call runtime.<name>(...) so tests "
                "patch one seam (#176)"
            )


@pytest.mark.parametrize("path", _NATIVE_MODULES, ids=lambda p: p.name)
def test_native_module_spawns_no_subprocess_directly(path):
    # a direct subprocess spawn skips the #56 cleanup registry AND the conftest lock
    # runtime.tracked_run gives every other seam call (GATE-11). Only ast.Call nodes
    # are checked — a bare `subprocess.TimeoutExpired` exception-class reference
    # (shortcuts.py) is not a spawn and must not be flagged.
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr in _SPAWNERS
        ) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "subprocess"
            and _SPAWNERS.intersection(a.name for a in node.names)
        ):
            raise AssertionError(
                f"{path.name}:{node.lineno} spawns a process directly — call "
                "runtime.tracked_run(...) qualified so the conftest lock fakes or "
                "refuses it (GATE-11)"
            )


def test_the_tripwire_sees_the_native_modules():
    # A glob that matches nothing (or too few) would make every assertion above
    # vacuous — assert it actually sees the whole native plane, doctor.py and
    # shortcuts.py included (GATE-01 empty edge).
    assert len(_NATIVE_MODULES) >= 10
    names = {p.name for p in _NATIVE_MODULES}
    assert "doctor.py" in names
    assert "shortcuts.py" in names


# --- runtime lock self-tests (GATE-01, #176 runtime half) -----------------------------
#
# The AST tests above catch a *static* regression — a by-name import. They cannot
# catch a *new* test that calls ``runtime.<seam>`` qualified for real. That is what
# conftest.py's autouse ``_no_real_osascript`` fixture is for; these tests prove it
# actually fires, for each seam name.


@pytest.mark.parametrize(
    "seam",
    sorted(
        [
            "run_osascript",
            "body_file",
            "tracked_run",
            "photos_db",
            "automation_permission",
            "accessibility_trusted",
            "compose_insert",
        ]
    ),
)
def test_unit_tests_cannot_reach_a_seam_unfaked(seam):
    # a unit test that forgets to fake a seam must fail closed, not spawn a real
    # process or write a real tempfile against a live app.
    with pytest.raises(AssertionError, match=seam):
        getattr(runtime, seam)("x")


def test_a_test_fake_overrides_the_lock(monkeypatch):
    # a test's own monkeypatch of a seam name overrides the autouse lock (the lock
    # applies first, so whatever a test sets afterwards is what runs) — this is what
    # lets every other test in the suite fake the seam it needs instead of being
    # permanently refused.
    def fake(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(runtime, "body_file", fake)
    assert runtime.body_file is fake


# --- store lock self-tests (FIX-35, #581) ---------------------------------------------
#
# conftest.py's autouse ``_no_real_stores`` fixture keeps a unit test off the real app
# stores of the Mac: each home-anchored path is a temp path or ``None``, and a read or
# a change under a real store area fails the test. No test below touches a real file:
# the refusal is called by hand, or it runs live on a temp folder.

_HOME = pathlib.Path.home()
_MAIL = _HOME / "Library" / "Mail"


class _Node:
    """What the lock reads of a test item: its markers and its stash."""

    def __init__(self, *markers, keywords=()):
        self._markers = markers
        self.keywords = dict.fromkeys(keywords, True)
        self.stash = pytest.Stash()

    def get_closest_marker(self, name):
        return name if name in self._markers else None


def _under(path, folder) -> bool:
    return pathlib.Path(folder) in pathlib.Path(path).parents


def _finished(lock) -> None:
    with pytest.raises(StopIteration):  # the teardown passes
        next(lock)


def test_real_store_lock_moves_each_store_path_off_the_home_folder(_isolated_state):
    paths = (
        notes.NOTESTORE,
        messages.CHAT_DB,
        reminders_store._STORES,
        runtime._PHOTOS_PREFS,
    )
    for path in paths:
        assert _under(path, _isolated_state)
        assert not _under(path, _HOME)
        assert not path.exists()
        assert not path.parent.exists()  # the lock never creates a store folder


def test_real_store_lock_gives_no_mail_index_and_no_mail_root():
    assert mail_index.envelope_index_path() is None
    assert mail_index.mail_root() is None


def test_real_store_lock_moves_the_file_root(_isolated_state):
    assert _under(files.root(), _isolated_state)
    assert files.root() != _HOME / "Downloads"


def test_real_store_lock_patches_by_name_copies():
    # The fixture looks for a copy under the original name only. This scan reads every
    # attribute, so a copy under another name (``import … as``) fails here.
    real = conftest.REAL_STORE_OBJECTS
    assert sorted(real) == [
        "CHAT_DB",
        "NOTESTORE",
        "_PHOTOS_PREFS",
        "_STORES",
        "envelope_index_path",
        "mail_root",
    ]
    # the captured objects are the real ones: a path under the home, or the function
    assert all(_under(v, _HOME) for k, v in real.items() if k.isupper())
    assert real["mail_root"].__module__ == mail_index.__name__
    copies = [
        f"{name}.{attr}"
        for name, mod in list(sys.modules.items())
        if name.startswith("macos_apps_mcp")
        for attr, value in list(vars(mod).items())
        if any(value is original for original in real.values())
    ]
    assert copies == []


def test_real_store_lock_replaces_and_restores_a_by_name_copy(
    _isolated_state, monkeypatch
):
    # The package holds no copy by name today, so a made-up module stands in for one.
    real = conftest.REAL_STORE_OBJECTS
    copy = types.ModuleType("macos_apps_mcp._made_up_by_name_copy")
    copy.NOTESTORE = real["NOTESTORE"]
    copy.mail_root = real["mail_root"]
    monkeypatch.setitem(sys.modules, copy.__name__, copy)
    patch = pytest.MonkeyPatch()
    lock = conftest._store_lock(_Node(), patch, _isolated_state)
    next(lock)
    assert _under(copy.NOTESTORE, _isolated_state)
    assert copy.mail_root() is None
    _finished(lock)
    patch.undo()
    assert copy.NOTESTORE is real["NOTESTORE"]
    assert copy.mail_root is real["mail_root"]


def test_real_store_lock_yields_to_a_tests_own_patch(monkeypatch, tmp_path):
    db = tmp_path / "Envelope Index"
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert mail_index.envelope_index_path() == db


def test_real_store_lock_watches_exactly_these_areas():
    shown = conftest._store_areas(_HOME, "/elsewhere/tests/conftest.py").values()
    assert sorted(shown) == [
        "/Library/Application Support/com.apple.TCC",
        "~/.local/state/macos-apps-mcp",
        "~/Downloads",
        "~/Library/Application Support/com.apple.TCC",
        "~/Library/Containers/com.apple.Photos",
        "~/Library/Group Containers",
        "~/Library/Mail",
        "~/Library/Messages",
    ]
    live = conftest._store_areas(_HOME, conftest.__file__)
    assert live == conftest._REAL_STORE_AREAS


def test_real_store_lock_leaves_out_an_area_that_holds_the_checkout():
    # A checkout in ~/Downloads: with that area watched, every read of the repo fails.
    home = pathlib.Path("/made-up-home")
    inside = conftest._store_areas(home, f"{home}/Downloads/repo/tests/conftest.py")
    assert "~/Downloads" not in inside.values()
    assert len(inside) == 7 and inside["/made-up-home/library/mail"] == "~/Library/Mail"
    # a folder beside the area is not inside it
    beside = conftest._store_areas(home, f"{home}/Downloads2/repo/tests/conftest.py")
    assert "~/Downloads" in beside.values() and len(beside) == 8


def _event_args(event: str, position: int, target) -> tuple:
    """The arguments of ``event`` with ``target`` at one of its path positions."""
    args = ["/made-up/other"] * conftest._STORE_EVENTS[event]
    args[position] = target
    return (*args, -1)


_PATH_POSITIONS = sorted(
    (event, position)
    for event, count in conftest._STORE_EVENTS.items()
    for position in range(count)
)


def test_real_store_lock_watches_reads_and_changes():
    # the events that write or delete are in the table, each path argument counted
    assert conftest._STORE_EVENTS == {
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


@pytest.mark.parametrize(("event", "position"), _PATH_POSITIONS)
def test_real_store_lock_refuses_each_event_in_each_real_area(
    _no_real_stores, event, position
):
    # The hook is called by hand: no system call is made, so no real file is touched.
    areas = conftest._store_areas(_HOME, "/elsewhere/tests/conftest.py")
    assert len(areas) == 8
    for area, shown in areas.items():
        for target in (f"{area}/x", f"{area}/x".encode(), pathlib.Path(area, "x")):
            with pytest.raises(conftest.RealStoreReached, match="real app store"):
                conftest._refuse_real_store(event, _event_args(event, position, target))
            assert _no_real_stores.pop() == f"{event} under {shown}"
    assert _no_real_stores == []
    # a file descriptor, and a path outside every area, pass
    conftest._refuse_real_store(event, _event_args(event, position, 7))
    conftest._refuse_real_store(event, _event_args(event, position, "/made-up/x"))
    assert _no_real_stores == []


_MAIL_SPELLINGS = {
    "plain": lambda: f"{_MAIL}/x",
    "the area itself": lambda: str(_MAIL),
    "relative": lambda: os.path.relpath(_MAIL / "x"),
    "dot-dot": lambda: f"{_HOME}/Library/../Library/Mail/x",
    "another letter case": lambda: f"{_MAIL}/x".swapcase(),
    "the Data volume alias": lambda: f"/System/Volumes/Data{_MAIL}/x",
    "the alias in another case": lambda: f"/system/volumes/DATA{_MAIL}/x",
}
_MAIL_URIS = {
    "file:/": lambda: f"file:{_MAIL}/x?mode=ro",
    "file:///": lambda: f"file://{_MAIL}/x?mode=ro",
    "file://localhost/": lambda: f"file://localhost{_MAIL}/x",
    "percent-encoded": lambda: f"file:{_MAIL}/x".replace("Mail", "%4Dail"),
    "relative URI": lambda: "file:" + os.path.relpath(_MAIL / "x") + "?mode=ro",
    "URI of the alias": lambda: f"file:///System/Volumes/Data{_MAIL}/x#frag",
}


@pytest.mark.parametrize("spelling", sorted(_MAIL_SPELLINGS))
def test_real_store_lock_sees_each_spelling_of_a_path(_no_real_stores, spelling):
    target = _MAIL_SPELLINGS[spelling]()
    for event in ("open", "os.remove"):
        with pytest.raises(conftest.RealStoreReached):
            conftest._refuse_real_store(event, (target, -1))
        assert _no_real_stores.pop() == f"{event} under ~/Library/Mail"


@pytest.mark.parametrize("form", sorted(_MAIL_URIS))
def test_real_store_lock_sees_each_form_of_a_sqlite_uri(_no_real_stores, form):
    with pytest.raises(conftest.RealStoreReached):
        conftest._refuse_real_store("sqlite3.connect", (_MAIL_URIS[form](),))
    assert _no_real_stores.pop() == "sqlite3.connect under ~/Library/Mail"


@pytest.mark.parametrize(
    "beside",
    ["Library/Mailboxes/x", "Library/Mail Downloads/x", "Library/Mai", "Downloads2/x"],
)
def test_real_store_lock_needs_a_path_separator_after_the_area(_no_real_stores, beside):
    # ~/Library/Mailboxes is not under ~/Library/Mail
    for event, count in conftest._STORE_EVENTS.items():
        conftest._refuse_real_store(event, (*[f"{_HOME}/{beside}"] * count, -1))
    conftest._refuse_real_store("sqlite3.connect", (f"file:{_HOME}/{beside}?mode=ro",))
    assert _no_real_stores == []


def test_real_store_lock_names_the_area_with_a_tilde_after_a_home_change(
    _no_real_stores, monkeypatch, tmp_path
):
    # A test that sets HOME must not make the refusal print the real home path.
    monkeypatch.setenv("HOME", str(tmp_path))
    assert pathlib.Path.home() == tmp_path
    with pytest.raises(conftest.RealStoreReached) as refused:
        conftest._refuse_real_store("open", (f"{_MAIL}/x", "r", 0))
    assert "(open under ~/Library/Mail)" in str(refused.value)
    assert str(_HOME) not in str(refused.value)
    assert _no_real_stores.pop() == "open under ~/Library/Mail"


def test_real_store_lock_is_live_on_reads_changes_and_a_symlink(
    _no_real_stores, monkeypatch, tmp_path
):
    # End to end through the interpreter's audit events, with a temp folder as the one
    # watched area: a refusal that only works when it is called by hand cannot pass.
    watched = tmp_path / "watched"
    (watched / "sub").mkdir(parents=True)
    db = watched / "db.sqlite"
    db.write_bytes(b"kept")
    link = tmp_path / "link"
    link.symlink_to(watched)  # made before the folder is watched
    outside = tmp_path / "outside"
    outside.write_bytes(b"o")
    monkeypatch.setattr(
        conftest, "_REAL_STORE_AREAS", {conftest._normal(str(watched)): "~/watched"}
    )
    refused = {
        "open": db.read_bytes,
        "open for a write": lambda: db.write_bytes(b"lost"),
        "open through a symlink": (link / "db.sqlite").read_bytes,
        "open in another letter case": pathlib.Path(str(db).swapcase()).read_bytes,
        "sqlite3.connect": lambda: sqlite3.connect(f"file://{db}?mode=ro", uri=True),
        "os.scandir": lambda: os.scandir(watched),
        "os.listdir": lambda: os.listdir(link),
        "os.remove": db.unlink,  # the incident: a test unlinked the live socket
        "os.rename from": lambda: db.rename(tmp_path / "moved"),
        "os.rename to": lambda: outside.replace(watched / "in"),
        "os.mkdir": lambda: (watched / "new").mkdir(),
        "os.mkdir of the area": lambda: watched.mkdir(parents=True, exist_ok=True),
        "os.rmdir": (watched / "sub").rmdir,
        "os.truncate": lambda: os.truncate(db, 0),
        "os.chmod": lambda: db.chmod(0o600),
        "os.chown": lambda: os.chown(db, os.getuid(), os.getgid()),
        "os.utime": lambda: os.utime(db),
        "os.symlink to": lambda: os.symlink(db, tmp_path / "second-link"),
        "os.symlink in": lambda: os.symlink(outside, watched / "ln"),
        "os.link": lambda: os.link(db, tmp_path / "hard"),
        "shutil.rmtree": lambda: shutil.rmtree(watched),
        "shutil.move": lambda: shutil.move(db, tmp_path / "moved"),
        "shutil.copyfile": lambda: shutil.copyfile(db, tmp_path / "copy"),
        "shutil.copytree": lambda: shutil.copytree(watched, tmp_path / "tree"),
    }
    for name, act in refused.items():
        with pytest.raises(conftest.RealStoreReached, match="real app store"):
            act()
        event = name.split(" ")[0]
        assert _no_real_stores.pop() == f"{event} under ~/watched", name
    assert _no_real_stores == []
    monkeypatch.undo()  # the folder is not watched now: look at what is left
    assert db.read_bytes() == b"kept"  # nothing was removed, moved or written
    assert sorted(p.name for p in watched.iterdir()) == ["db.sqlite", "sub"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["link", "outside", "watched"]


def test_real_store_lock_fails_a_test_that_swallowed_the_refusal(
    _no_real_stores, _isolated_state, monkeypatch
):
    # The code under test may catch the refusal (``except Exception``). The lock keeps
    # each one and fails the test at teardown. A second lock is run by hand here.
    lock = conftest._store_lock(_Node(), monkeypatch, _isolated_state)
    hits = next(lock)
    with contextlib.suppress(AssertionError):  # the code under test swallows it
        conftest._refuse_real_store("os.remove", (f"{_MAIL}/x", -1))
    assert hits == ["os.remove under ~/Library/Mail"]
    with pytest.raises(
        conftest.RealStoreReached,
        match="real app store .os.remove under ~/Library/Mail",
    ):
        next(lock)
    assert conftest._store_hits is _no_real_stores  # this test's lock is back
    assert _no_real_stores == []

    clean = conftest._store_lock(_Node(), monkeypatch, _isolated_state)
    next(clean)
    _finished(clean)  # no refused read: the teardown passes


def _report(node, when: str, error: BaseException) -> None:
    """Run conftest's report hook by hand for a test phase that ended in ``error``."""
    with pytest.raises(type(error)) as raised:
        raise error
    hook = conftest.pytest_runtest_makereport(
        node, types.SimpleNamespace(when=when, excinfo=raised)
    )
    next(hook)
    with pytest.raises(StopIteration) as done:
        hook.send("the report")
    assert done.value.value == "the report"


def test_real_store_lock_reports_one_failure_for_one_refused_read(
    _isolated_state, monkeypatch
):
    # A refusal that the test body did not catch already fails the test: the teardown
    # must not add an ERROR line for the same read.
    def teardown_after(when, error):
        node = _Node()
        lock = conftest._store_lock(node, monkeypatch, _isolated_state)
        next(lock).append("open under ~/Library/Mail")
        _report(node, when, error)
        return lock

    _finished(teardown_after("call", conftest.RealStoreReached("refused")))
    # another failure of the body, or a refusal in the setup, hides nothing
    for when, error in (
        ("call", ValueError("another failure")),
        ("setup", conftest.RealStoreReached("refused")),
    ):
        with pytest.raises(conftest.RealStoreReached, match="real app store"):
            next(teardown_after(when, error))


def test_real_store_lock_exempts_a_test_marked_integration_only(
    _no_real_stores, _isolated_state, monkeypatch
):
    # An integration test must read the real stores. The real path object goes back
    # for this check; nothing opens it.
    real = conftest.REAL_STORE_OBJECTS["NOTESTORE"]
    monkeypatch.setattr(notes, "NOTESTORE", real)
    exempt = conftest._store_lock(_Node("integration"), monkeypatch, _isolated_state)
    assert next(exempt) is None
    assert notes.NOTESTORE is real
    assert conftest._store_hits is _no_real_stores  # no second refusal list
    _finished(exempt)

    for node in (
        _Node("device"),
        # the word in the keywords is not the marker: a parametrize id, a function
        # attribute, or a test file in a folder named ``integration``
        _Node(keywords=["integration", "tests/integration/test_x.py"]),
    ):
        monkeypatch.setattr(notes, "NOTESTORE", real)
        locked = conftest._store_lock(node, monkeypatch, _isolated_state)
        assert next(locked) == []
        assert notes.NOTESTORE is not real
        _finished(locked)


@pytest.mark.parametrize("case", ["a parametrize id"], ids=["integration"])
def test_real_store_lock_keeps_a_test_whose_parametrize_id_is_integration(
    request, case
):
    assert "integration" in request.keywords  # why the keywords are not the test
    assert not conftest._is_integration(request.node)
    assert notes.NOTESTORE is not conftest.REAL_STORE_OBJECTS["NOTESTORE"]
    with pytest.raises(AssertionError, match="run_osascript"):  # the older lock too
        runtime.run_osascript("x")


def test_real_store_lock_leaves_other_paths_alone(tmp_path):
    (tmp_path / "f").write_text("x")
    assert (tmp_path / "f").read_text() == "x"
    assert os.listdir(tmp_path) == ["f"]
    (tmp_path / "f").unlink()
    (tmp_path / "d").mkdir()
    shutil.rmtree(tmp_path / "d")
