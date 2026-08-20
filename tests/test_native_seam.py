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
