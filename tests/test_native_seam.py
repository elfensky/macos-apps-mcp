"""#176: the mail adapters reach the native seam QUALIFIED — ``runtime.run_osascript``.

``from ..runtime import run_osascript`` lands a *copy* of the seam in the importing
module's namespace, so a test has to fake it once per module — and a forgotten module
fails OPEN: the call spawns osascript against real Mail (that is #160, where a send
tool did exactly that). Qualified calls mean one patch point, ``runtime``, however many
modules the mail adapter splits into.

Every ``adapters/mail*.py`` is covered, so the modules #178 splits out inherit the rule
without anyone remembering to add them here.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from macos_apps_mcp import runtime

_SEAM = frozenset({"run_osascript", "body_file"})
_MAIL_MODULES = sorted(
    (pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters").glob(
        "mail*.py"
    )
)


@pytest.mark.parametrize("path", _MAIL_MODULES, ids=lambda p: p.name)
def test_mail_module_does_not_import_the_seam_by_name(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("runtime"):
            offenders = _SEAM.intersection(a.name for a in node.names)
            assert not offenders, (
                f"{path.name}:{node.lineno} imports {sorted(offenders)} by name — "
                "use `from .. import runtime` and call runtime.<name>(...) so tests "
                "patch one seam (#176)"
            )


def test_the_tripwire_sees_the_mail_modules():
    # A glob that matches nothing would make every assertion above vacuous.
    assert len(_MAIL_MODULES) >= 3


# --- runtime lock self-tests (GATE-01, #176 runtime half) -----------------------------
#
# The AST tests above catch a *static* regression — a by-name import. They cannot
# catch a *new* test that calls ``runtime.<seam>`` qualified for real. That is what
# conftest.py's autouse ``_no_real_osascript`` fixture is for; these tests prove it
# actually fires, for each of the three seam names.


@pytest.mark.parametrize("seam", sorted(["run_osascript", "body_file", "tracked_run"]))
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
