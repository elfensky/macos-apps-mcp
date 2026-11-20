"""Scripts address an app by its bundle id, never by its name (#585).

With Mail closed, the name "Mail" resolved to a helper bundle of the same name, and
every Mail script failed to compile. This file holds the Mail part of the guard, over
the one script inventory (``tests.scripts.templates()``).
"""

from __future__ import annotations

import re

import pytest

from macos_apps_mcp import runtime
from tests import scripts

_SCRIPTS = scripts.templates()
_ID_LITERAL = re.compile(r'application id "([^"]*)"')
_MAIL_BY_NAME = 'tell application "Mail"'
_MAIL_BY_ID = f'tell application id "{runtime.BUNDLE_IDS["Mail"]}"'
# Well under today's count (37 scripts hold a Mail target), well over a broken walk.
_MIN_MAIL_SCRIPTS = 30


def test_the_guard_reaches_the_mail_scripts():
    # an inventory with no Mail script would make both checks below vacuous
    by_id = [name for name, src in _SCRIPTS.items() if _MAIL_BY_ID in src]
    assert len(by_id) >= _MIN_MAIL_SCRIPTS, sorted(by_id)
    assert "runtime._ACTIVATE_WINDOW" in by_id and "runtime._WINDOW_INDEX" in by_id


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_no_script_addresses_mail_by_name(name):
    assert _MAIL_BY_NAME not in _SCRIPTS[name]


@pytest.mark.parametrize("name", sorted(_SCRIPTS))
def test_every_id_literal_is_a_bundle_id_of_the_table(name):
    # EXACT, case included: `com.apple.Mail` compiles too; the table has one spelling
    known = set(runtime.BUNDLE_IDS.values())
    unknown = set(_ID_LITERAL.findall(_SCRIPTS[name])) - known
    assert not unknown, f"{name}: ids outside runtime.BUNDLE_IDS: {sorted(unknown)}"


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
