"""FIX-35 (#581) probe: is any AppleScript of the package outside the script inventory?

Three checks against ``tests/scripts.py`` (the one inventory of PR #584):

1. Every string constant in the package source that looks like AppleScript and is not
   part of an inventory template.
2. Every ``run_osascript`` call site whose template is not in the compile inventory.
3. Every inventory template that no call site passes (handler fragments).

Run from the repo root:  uv run python <this file>

Reads source text and imports the package. It compiles nothing and starts nothing.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

sys.path.insert(0, ".")

import macos_apps_mcp  # noqa: E402
from tests import scripts  # noqa: E402
from tests import test_applescript_timeout as tripwire  # noqa: E402

_LOOKS_LIKE = re.compile(
    r"\bon run\b|\bend tell\b|tell application|\bon error\b|display alert|"
    r"display dialog|\bend try\b"
)


def main() -> None:
    templates = scripts.templates()
    sources = set(templates.values())
    print("inventory templates:", len(templates))

    root = pathlib.Path(macos_apps_mcp.__file__).parent
    print("1. AppleScript-like string constants outside every template:")
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value
            if id(node) in docstrings or not _LOOKS_LIKE.search(text):
                continue
            if not any(text in source for source in sources):
                where = path.relative_to(root.parent)
                print(f"   {where}:{node.lineno}: {text[:80]!r}")

    names = {label.split(".", 1)[1] for label in templates}
    called = {site.template_label.split(".")[-1] for site in tripwire._CALL_SITES}
    print("call sites:", len(tripwire._CALL_SITES))
    print("2. call-site templates outside the compile inventory:", sorted(called - names))
    print("3. inventory templates with no call site:", sorted(names - called))


if __name__ == "__main__":
    main()
