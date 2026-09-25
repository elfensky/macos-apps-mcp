"""Layering test (GATE-03): nothing BELOW server.py imports server.py.

Card 5 removed the package's only import cycle — doctor.py's lazy
``from . import server`` inside ``_outbound_state()``. This test pins the
invariant generally instead of just re-testing that one call site: it computes
``server.py``'s own module-level import closure (what actually runs at import
time — top-level statements only), then walks EVERY module in that closure —
function bodies included, since a lazy/local import is exactly how the old
cycle hid — and fails if any import anywhere resolves back to
``macos_apps_mcp.server``.

The one place the package legitimately imports server from "below" is an
ENTRY POINT launching the program it runs — ``daemon.serve()`` imports the
server it serves (``from .server import mcp``), and ``deploy.py`` imports
``daemon.socket_path`` lazily. Neither of those is server's own import
closure reaching back into itself; they are the reverse direction (something
outside the closure importing INTO it to run it), which is why this test's
rule is precisely "nothing BELOW server imports server", not "server is
imported nowhere in the package".
"""

from __future__ import annotations

import ast
from pathlib import Path

import macos_apps_mcp

PACKAGE_ROOT = Path(macos_apps_mcp.__file__).parent
PACKAGE_NAME = "macos_apps_mcp"
SERVER_MODULE = f"{PACKAGE_NAME}.server"


def _module_name_for(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_for(module_name: str, is_package: bool) -> str:
    if is_package or "." not in module_name:
        return module_name
    return module_name.rsplit(".", 1)[0]


def _resolve_import_node(node: ast.AST, pkg: str) -> set[str]:
    """Every dotted name `node` resolves to — the resolved base module AND
    base+alias forms, so both `from .server import mcp` (base alone) and
    `from . import server` (base+alias) are caught."""
    resolved: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            resolved.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0:
            base = node.module or ""
            if base:
                resolved.add(base)
        else:
            parts = pkg.split(".") if pkg else []
            truncate = node.level - 1
            if truncate:
                parts = parts[:-truncate] if truncate < len(parts) else []
            base = ".".join(parts)
            if node.module:
                base = f"{base}.{node.module}" if base else node.module
                resolved.add(base)
            # else: bare `from . import X` — `base` alone is just this file's own
            # current package, true of nearly every relative import in the
            # package and not a meaningful edge; only base+alias below matters.
        for alias in node.names:
            resolved.add(f"{base}.{alias.name}" if base else alias.name)
    return resolved


def _imports_in(nodes, pkg: str) -> set[str]:
    result: set[str] = set()
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            result |= _resolve_import_node(node, pkg)
    return result


class _ModuleInfo:
    __slots__ = ("path", "pkg", "top_level_imports", "import_nodes")

    def __init__(self, path: Path, pkg: str, top_level_imports: set[str], import_nodes):
        self.path = path
        self.pkg = pkg
        self.top_level_imports = top_level_imports
        self.import_nodes = import_nodes


def _load_modules() -> dict[str, _ModuleInfo]:
    modules: dict[str, _ModuleInfo] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _module_name_for(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        is_package = path.name == "__init__.py"
        pkg = _package_for(name, is_package)
        top_level_imports = _imports_in(tree.body, pkg)
        import_nodes = [
            n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        modules[name] = _ModuleInfo(path, pkg, top_level_imports, import_nodes)
    return modules


def _import_closure(modules: dict[str, _ModuleInfo], start: str) -> set[str]:
    """The transitive module-level import closure of `start`, restricted to
    modules that live inside the package (external deps are leaves)."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        info = modules.get(cur)
        if info is None:
            continue
        for imp in info.top_level_imports:
            if imp in modules and imp not in seen:
                stack.append(imp)
    return seen


def test_nothing_below_server_imports_server():
    modules = _load_modules()
    assert SERVER_MODULE in modules, "server.py not found by the module scanner"
    closure = _import_closure(modules, SERVER_MODULE)
    violations = []
    for name in sorted(closure - {SERVER_MODULE}):
        info = modules[name]
        for node in info.import_nodes:
            resolved = _resolve_import_node(node, info.pkg)
            if SERVER_MODULE in resolved:
                violations.append(f"{name}:{node.lineno}")
    assert not violations, (
        "module(s) below server.py import server.py (GATE-03 back-edge): "
        + ", ".join(violations)
    )


def test_layering_closure_is_not_vacuous():
    """The closure above must contain real modules, or the first test would pass
    trivially by finding nothing to check."""
    modules = _load_modules()
    closure = _import_closure(modules, SERVER_MODULE)
    for expected in (
        f"{PACKAGE_NAME}.doctor",
        f"{PACKAGE_NAME}.deploy",
        f"{PACKAGE_NAME}.audit",
        f"{PACKAGE_NAME}.runtime",
        f"{PACKAGE_NAME}.tiers",
    ):
        assert expected in closure, f"{expected} missing from server's import closure"
