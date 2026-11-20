"""Scripts address an app by its bundle id, never by its name (#585).

With Mail closed, the name "Mail" resolved to a helper bundle of the same name, and
every Mail script failed to compile. On the checked Mac, nested bundles of Notes,
Messages and Music carry the app's name in their display name. No name collision was
observed for the other five apps: for them the id form is a precaution, and it gives
one rule for every app.

The guard reads two inputs:

- the script inventory (``tests.scripts.templates()``): the final text of each
  module-level script constant, after the f-strings and joins that Python resolves
  at import;
- the text of every text file of the package, ``.py`` or not, so a script that is
  built inline or kept in a script file is seen too.

On both inputs: no target by name (``application "<x>"``, the ``app`` short form
included), and each id literal is a value of ``runtime.BUNDLE_IDS``. On the inventory
only: each ``tell`` of an app has the one form that ``runtime._TELL_APP`` reads,
``tell application id "<table value>"``, or takes its id from ``argv``. So a target in
a variable (``set a to "Notes"``, then ``tell application a``), on a continuation
line, or in the short form fails there. The file text is not held to that form: it
holds the regex text of ``runtime._TELL_APP``.

What no check here sees:

- an inline script (in no inventory) whose target is not one quoted literal: an
  f-string field in place of the whole target, a ``+`` join, a variable, a
  continuation line;
- a variable target with no ``tell application`` (``set a to application n``, then
  ``tell a``);
- a compiled script file: it is binary, and no regex reads it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import macos_apps_mcp
from macos_apps_mcp import runtime
from tests import scripts

_APP = r"\b(?:application|app)"
# A by-name target: `application` or `app`, then any quoted text on the same line (a
# name, a name with a dot or a digit, a path). It reads a `tell`, a `path to
# application` and an `is running` test alike. The regex text of `runtime._TELL_APP`
# holds no quote after the word, so it does not match.
_BY_NAME = re.compile(_APP + r'\s+"[^"\n]*"')
# An id literal, with any spacing before the quote: `application id "<x>"`.
_ID_LITERAL = re.compile(_APP + r'\s+id\s*"([^"]*)"')
_KNOWN_IDS = set(runtime.BUNDLE_IDS.values())
# A `tell` of an app, to the end of its line, and the forms it may have.
_TELL = re.compile(r"\btell\s+app(?:lication)?\b[^\n]*")
_ID_ALTERNATIVES = "|".join(map(re.escape, sorted(_KNOWN_IDS)))
_TELL_OK = re.compile(
    rf'tell application id (?:"(?:{_ID_ALTERNATIVES})"|\(item \d+ of argv\))'
)
# Exceptions: `"<label>: <match>"` (as a check reports it) -> the reason.
# Empty, and no entry is expected.
_ALLOWED: dict[str, str] = {}
_HOW = (
    'address the app by `tell application id "<bundle id>"`; '
    "the ids are in runtime.BUNDLE_IDS"
)
_MAIL_BY_NAME = 'tell application "Mail"'
_MAIL_BY_ID = f'tell application id "{runtime.BUNDLE_IDS["Mail"]}"'
# Well under today's count (37 scripts hold a Mail target), well over a broken walk.
_MIN_MAIL_SCRIPTS = 30
# Well under today's count of id-form targets in the package text (59: Mail 40, the
# other five apps 19), well over a broken scan.
_MIN_ID_TARGETS = 50


def package_text(root: pathlib.Path) -> dict[str, str]:
    """``{relative path: text}`` for every text file under ``root``.

    By file scan, never by import: ``__main__.py`` and a non-Python file are read
    too. A file that is not UTF-8 text is left out (see the module docstring).
    """
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            found[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return found


_SCRIPTS = scripts.templates()
_SOURCES = package_text(pathlib.Path(macos_apps_mcp.__file__).parent)


def _hits(sources: dict[str, str], pattern: re.Pattern, fine=lambda m: False):
    """``"<label>: <match>"`` per match that is not ``fine``, less ``_ALLOWED``."""
    found = {
        f"{label}: {match.group()}"
        for label, source in sources.items()
        for match in pattern.finditer(source)
        if not fine(match)
    }
    return sorted(found - _ALLOWED.keys())


def by_name_targets(sources: dict[str, str]) -> list[str]:
    """Each target that names an app by a quoted name."""
    return _hits(sources, _BY_NAME)


def unknown_ids(sources: dict[str, str]) -> list[str]:
    """Each id literal that is not EXACTLY a value of the table, case included:
    `com.apple.Mail` compiles too, and the table has one spelling."""
    return _hits(sources, _ID_LITERAL, lambda m: m.group(1) in _KNOWN_IDS)


def unread_tells(sources: dict[str, str]) -> list[str]:
    """Each ``tell`` of an app that ``runtime._TELL_APP`` cannot resolve to a table
    id: a variable target, a continuation line, the short form, other spacing."""
    return _hits(sources, _TELL, lambda m: _TELL_OK.match(m.group()))


def test_the_addressing_guard_finds_the_scripts():
    # an empty inventory or an empty file scan would make every check below vacuous
    assert len(_SCRIPTS) >= scripts.MIN_TEMPLATES
    by_id = [i for source in _SOURCES.values() for i in _ID_LITERAL.findall(source)]
    assert len(by_id) >= _MIN_ID_TARGETS, (
        f"the scan of the package text found {len(by_id)} id-form targets, under "
        f"the floor of {_MIN_ID_TARGETS}. The floor proves that the scan reaches "
        "the scripts; lower it when scripts are removed on purpose."
    )
    tells = [t for source in _SCRIPTS.values() for t in _TELL.findall(source)]
    assert len(tells) >= _MIN_ID_TARGETS, len(tells)


def test_the_guard_reaches_the_mail_scripts():
    # an inventory with no Mail script would make both checks below vacuous
    by_id = [name for name, src in _SCRIPTS.items() if _MAIL_BY_ID in src]
    assert len(by_id) >= _MIN_MAIL_SCRIPTS, sorted(by_id)
    assert "runtime._ACTIVATE_WINDOW" in by_id and "runtime._WINDOW_INDEX" in by_id


def test_no_script_names_an_app_by_name():
    offenders = by_name_targets(_SCRIPTS)
    assert not offenders, f"{offenders}: {_HOW}"


def test_no_package_source_names_an_app_by_name():
    # every text file of the package, so a script built inline (in no inventory) or
    # kept in a script file is seen
    offenders = by_name_targets(_SOURCES)
    assert not offenders, f"{offenders}: {_HOW}"


def test_every_tell_of_a_script_names_a_table_id():
    # the final script texts: a variable target, a continuation line and the short
    # form compile, and the timeout hint could not name their process
    offenders = unread_tells(_SCRIPTS)
    assert not offenders, f"{offenders}: {_HOW}"


def test_the_addressing_guard_fails_on_a_by_name_script():
    by_name = {
        "made.UP": 'tell application "Notes"\nend tell',
        "made.SHORT": 'tell app "Notes" to return 1',
        "made.DOT": 'tell application "Notes.app" to return 1',
        "made.DIGIT": 'tell application "Safari 2" to return 1',
        "made.PATH": 'tell application "/System/Applications/Notes.app" to return 1',
        "made.RUNNING": 'if application "System Events" is running then return',
        "made.FIELD": 'tell application "{name}" to return 1',
    }
    assert by_name_targets(by_name) == [
        'made.DIGIT: application "Safari 2"',
        'made.DOT: application "Notes.app"',
        'made.FIELD: application "{name}"',
        'made.PATH: application "/System/Applications/Notes.app"',
        'made.RUNNING: application "System Events"',
        'made.SHORT: app "Notes"',
        'made.UP: application "Notes"',
    ]
    assert by_name_targets({"made.BY_ID": f"{_MAIL_BY_ID}\nend tell"}) == []


def test_the_addressing_guard_fails_on_an_id_outside_the_table():
    wrong = {
        "made.CASE": 'tell application id "com.apple.notes" to return 1',
        "made.TWO_SPACES": 'tell application id  "com.example.none" to return 1',
        "made.NO_SPACE": 'tell application id"com.example.none" to return 1',
        "made.SHORT": 'tell app id "com.example.none" to return 1',
        "made.FIELD": 'tell application id "{bundle}" to return 1',
    }
    assert unknown_ids(wrong) == [
        'made.CASE: application id "com.apple.notes"',
        'made.FIELD: application id "{bundle}"',
        'made.NO_SPACE: application id"com.example.none"',
        'made.SHORT: app id "com.example.none"',
        'made.TWO_SPACES: application id  "com.example.none"',
    ]
    assert unknown_ids({"made.BY_ID": f"{_MAIL_BY_ID}\nend tell"}) == []


def test_the_addressing_guard_fails_on_a_tell_it_cannot_read():
    notes = runtime.BUNDLE_IDS["Notes"]
    unread = {
        "made.VARIABLE": 'set a to "Notes"\ntell application a\nend tell',
        "made.CONTINUED": 'tell application ¬\n  "Notes"\nend tell',
        "made.SHORT": f'tell app id "{notes}" to return 1',
        "made.SPACED": f'tell application  id "{notes}"',
        "made.NAME_BY_ARGV": "tell application (item 1 of argv) to return 1",
    }
    assert unread_tells(unread) == [
        "made.CONTINUED: tell application ¬",
        "made.NAME_BY_ARGV: tell application (item 1 of argv) to return 1",
        f'made.SHORT: tell app id "{notes}" to return 1',
        f'made.SPACED: tell application  id "{notes}"',
        "made.VARIABLE: tell application a",
    ]
    fine = {
        "made.BY_ID": f"{_MAIL_BY_ID} to return 1",
        "made.ID_BY_ARGV": "tell application id (item 1 of argv) to return 1",
        "made.OBJECT": "tell front window\nend tell",
    }
    assert unread_tells(fine) == []


def test_the_file_scan_reads_a_script_file_that_is_not_python(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "made_up.applescript").write_text('tell app "Notes"\nend tell')
    (tmp_path / "icon.bin").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text('tell application "Notes"')
    text = package_text(tmp_path)
    assert sorted(text) == ["sub/made_up.applescript"]
    assert by_name_targets(text) == ['sub/made_up.applescript: app "Notes"']


def test_the_inventory_finds_a_short_form_script(monkeypatch):
    # a `tell app` script must not skip the compile check and the timeout tripwires
    # (a text of its own: the inventory lists a repeated value once, under one name)
    made_up = '-- made up for this test\ntell app "Notes"\nend tell'
    monkeypatch.setattr(runtime, "MADE_UP_SHORT", made_up, raising=False)
    assert scripts.templates().get("runtime.MADE_UP_SHORT") == made_up


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_no_script_addresses_mail_by_name(name):
    assert _MAIL_BY_NAME not in _SCRIPTS[name]


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_every_id_literal_is_a_bundle_id_of_the_table(name):
    unknown = unknown_ids({name: _SCRIPTS[name]})
    assert not unknown, f"ids outside runtime.BUNDLE_IDS: {unknown}"


def test_every_script_id_is_in_the_runtime_table():
    # the same rule over the package text, so an inline script cannot name an id
    # that the timeout hint cannot resolve to a process
    unknown = unknown_ids(_SOURCES)
    assert not unknown, f"ids outside runtime.BUNDLE_IDS: {unknown}"


def test_missing_apps_names_mail_for_an_id_form_script(monkeypatch, tmp_path):
    # the compile check skips a script whose app is absent; the id form must not
    # switch that branch off. An id outside the table is not "missing": it compiles.
    script = f"{_MAIL_BY_ID}\nend tell"
    monkeypatch.setattr(scripts, "_APP_DIRS", (tmp_path,))
    assert scripts.missing_apps(script) == ["Mail"]
    (tmp_path / "Mail.app").mkdir()
    assert scripts.missing_apps(script) == []
    assert scripts.missing_apps('tell application "Notes"\nend tell') == ["Notes"]
    assert scripts.missing_apps('tell application id "com.example.none"') == []
