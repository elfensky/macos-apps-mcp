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
import os
import pathlib
import sqlite3
import sys

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
# stores of the Mac: each home-anchored path is a temp path or ``None``, and an open of
# a real store area fails the test. No test below opens a real file.

_HOME = pathlib.Path.home()


def _under(path, folder) -> bool:
    return pathlib.Path(folder) in pathlib.Path(path).parents


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


def test_real_store_lock_yields_to_a_tests_own_patch(monkeypatch, tmp_path):
    db = tmp_path / "Envelope Index"
    monkeypatch.setattr(mail_index, "envelope_index_path", lambda: db)
    assert mail_index.envelope_index_path() == db


@pytest.mark.parametrize("event", sorted(conftest._STORE_EVENTS))
def test_real_store_lock_refuses_a_read_of_each_real_area(_no_real_stores, event):
    # The hook is called by hand: no open is tried, so no real file is touched.
    assert len(conftest._REAL_STORE_AREAS) >= 6
    for area in conftest._REAL_STORE_AREAS:
        for target in (f"{area}/x", f"{area}/x".encode(), pathlib.Path(area, "x")):
            with pytest.raises(AssertionError, match="real app store"):
                conftest._refuse_real_store(event, (target,))
    with pytest.raises(AssertionError, match="real app store"):  # the sqlite URI form
        area = next(a for a in conftest._REAL_STORE_AREAS if " " in a).replace(
            " ", "%20"
        )
        conftest._refuse_real_store(event, (f"file:{area}/x?mode=ro",))
    # the message names the area with ~ for the home, never the home path
    assert all(str(_HOME) not in hit for hit in _no_real_stores)
    assert any("under ~/Library/Mail" in hit for hit in _no_real_stores)
    _no_real_stores.clear()  # the refusals above are the point of this test


def test_real_store_lock_is_live_on_open_connect_and_scan(
    _no_real_stores, monkeypatch, tmp_path
):
    # End to end through the interpreter's audit events, with a temp folder as the one
    # watched area: a refusal that only works when it is called by hand cannot pass.
    watched = tmp_path / "watched"
    watched.mkdir()
    (watched / "db.sqlite").write_bytes(b"")
    monkeypatch.setattr(conftest, "_REAL_STORE_AREAS", (str(watched),))
    for read in (
        (watched / "db.sqlite").read_bytes,
        lambda: sqlite3.connect(f"file:{watched}/db.sqlite?mode=ro", uri=True),
        lambda: os.scandir(watched),
        lambda: os.listdir(watched),
    ):
        with pytest.raises(AssertionError, match="real app store"):
            read()
    assert len(_no_real_stores) == 4
    _no_real_stores.clear()


def test_real_store_lock_fails_a_test_that_swallowed_the_refusal():
    # Product code may catch the refusal (``except Exception``). The fixture keeps each
    # one and fails the test at teardown; this is the check it runs there.
    with pytest.raises(AssertionError, match="real app store"):
        conftest._fail_on_store_hits(["open under ~/Library/Mail"])
    conftest._fail_on_store_hits([])


def test_real_store_lock_leaves_other_paths_alone(tmp_path):
    (tmp_path / "f").write_text("x")
    assert (tmp_path / "f").read_text() == "x"
    assert os.listdir(tmp_path) == ["f"]
