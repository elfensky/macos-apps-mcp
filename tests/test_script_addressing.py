"""Scripts address an app by its bundle id, never by its name (#585).

With Mail closed, the name "Mail" resolved to a helper bundle of the same name, and
every Mail script failed to compile. Notes, Messages and Music hold nested bundles
with the app's name too. This file is the guard for every app: over the one script
inventory (``tests.scripts.templates()``) and over the source text of every file of
the package, so a script that is built inline is seen too.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import macos_apps_mcp
from macos_apps_mcp import runtime
from tests import scripts

_SCRIPTS = scripts.templates()
_PACKAGE = pathlib.Path(macos_apps_mcp.__file__).parent
# By file scan, never by import: `__main__.py` is read too.
_SOURCES = {
    path.relative_to(_PACKAGE).as_posix(): path.read_text(encoding="utf-8")
    for path in sorted(_PACKAGE.rglob("*.py"))
}
_ID_LITERAL = re.compile(r'application id "([^"]*)"')
# A by-name target: the word `application`, then a quoted name of letters and spaces.
# It reads a `tell`, a `path to application` and an `is running` test alike. The
# regex text of `runtime._TELL_APP` holds no such name, so it does not match.
_BY_NAME = re.compile(r'application\s+"[A-Za-z][A-Za-z ]*"')
# Exceptions: `"<label>: <match>"` (as `by_name_targets` reports it) -> the reason.
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
# The exact count today of id-form targets in the package source (Mail 40, the other
# five apps 19). Lower it when a script goes; raise it when one comes.
_MIN_ID_TARGETS = 59


def by_name_targets(sources: dict[str, str]) -> list[str]:
    """``"<label>: <match>"`` per by-name target of ``sources``, less ``_ALLOWED``."""
    found = {
        f"{label}: {match}"
        for label, source in sources.items()
        for match in _BY_NAME.findall(source)
    }
    return sorted(found - _ALLOWED.keys())


def test_the_addressing_guard_finds_the_scripts():
    # an empty inventory or an empty file scan would make every check below vacuous
    assert len(_SCRIPTS) >= scripts.MIN_TEMPLATES
    by_id = [i for source in _SOURCES.values() for i in _ID_LITERAL.findall(source)]
    assert len(by_id) >= _MIN_ID_TARGETS, len(by_id)


def test_the_guard_reaches_the_mail_scripts():
    # an inventory with no Mail script would make both checks below vacuous
    by_id = [name for name, src in _SCRIPTS.items() if _MAIL_BY_ID in src]
    assert len(by_id) >= _MIN_MAIL_SCRIPTS, sorted(by_id)
    assert "runtime._ACTIVATE_WINDOW" in by_id and "runtime._WINDOW_INDEX" in by_id


def test_no_script_names_an_app_by_name():
    offenders = by_name_targets(_SCRIPTS)
    assert not offenders, f"{offenders}: {_HOW}"


def test_no_package_source_names_an_app_by_name():
    # every file of the package, so a script built inline (in no inventory) is seen
    offenders = by_name_targets(_SOURCES)
    assert not offenders, f"{offenders}: {_HOW}"


def test_the_addressing_guard_fails_on_a_by_name_script():
    by_name = {
        "made.UP": 'tell application "Notes"\nend tell',
        "made.RUNNING": 'if application "System Events" is running then return',
    }
    assert by_name_targets(by_name) == [
        'made.RUNNING: application "System Events"',
        'made.UP: application "Notes"',
    ]
    assert by_name_targets({"made.BY_ID": f"{_MAIL_BY_ID}\nend tell"}) == []


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_no_script_addresses_mail_by_name(name):
    assert _MAIL_BY_NAME not in _SCRIPTS[name]


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_every_id_literal_is_a_bundle_id_of_the_table(name):
    # EXACT, case included: `com.apple.Mail` compiles too; the table has one spelling
    known = set(runtime.BUNDLE_IDS.values())
    unknown = set(_ID_LITERAL.findall(_SCRIPTS[name])) - known
    assert not unknown, f"{name}: ids outside runtime.BUNDLE_IDS: {sorted(unknown)}"


def test_every_script_id_is_in_the_runtime_table():
    # the same rule over the source text, so an inline script cannot name an id that
    # the timeout hint cannot resolve to a process
    known = set(runtime.BUNDLE_IDS.values())
    unknown = sorted(
        f"{path}: {found}"
        for path, source in _SOURCES.items()
        for found in set(_ID_LITERAL.findall(source)) - known
    )
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
