"""One inventory of the package's AppleScript, for every script guard (#581).

The compile check and both timeout tripwires read these. Discovery walks the whole
``macos_apps_mcp`` package by scan, never a hand list of modules: three hand lists
once left the scripts of eight modules, ``runtime`` among them, outside every guard.
A new module is covered the moment it exists; an exclusion is a commented entry in
``SKIP_MODULES``.
"""

from __future__ import annotations

import importlib
import pathlib
import pkgutil
import re

import macos_apps_mcp

# Modules the walk never imports, each with the reason.
SKIP_MODULES = {
    # importing it runs `main()`, which starts the stdio server
    "macos_apps_mcp.__main__": "importing it starts the server",
}

# The meta-guard floors: well under today's counts (57 scripts, 59 call sites), well
# over what a broken walk finds. Raise them when the package grows.
MIN_TEMPLATES = 50
MIN_CALL_SITES = 50

_APP_DIRS = (
    pathlib.Path("/System/Applications"),
    pathlib.Path("/Applications"),
    pathlib.Path("/System/Library/CoreServices"),
)
_TELL_RE = re.compile(r'tell application "([^"]+)"')


def modules():
    """(path, module) for every module of the package, minus ``SKIP_MODULES``."""
    for info in pkgutil.walk_packages(macos_apps_mcp.__path__, "macos_apps_mcp."):
        if info.name in SKIP_MODULES:
            continue
        mod = importlib.import_module(info.name)
        yield pathlib.Path(mod.__file__), mod


def templates() -> dict[str, str]:
    """``{"module.NAME": source}`` for each module-level script constant.

    A script constant is an uppercase name bound to a multi-line string that drives an
    app (``tell application``). A value one module re-exports from another counts once,
    under the first module the walk meets.
    """
    found: dict[str, str] = {}
    seen: set[str] = set()
    for _path, mod in modules():
        short = mod.__name__.removeprefix("macos_apps_mcp.").removeprefix("adapters.")
        for name, val in vars(mod).items():
            if not (name.isupper() and isinstance(val, str)):
                continue
            if "\n" not in val or "tell application" not in val or val in seen:
                continue
            seen.add(val)
            found[f"{short}.{name}"] = val
    return found


def missing_apps(source: str) -> list[str]:
    """Apps a script names by literal that this machine does not have.

    ``osacompile`` reads the target app's scripting dictionary, so a script for an
    absent app cannot compile here — the caller skips it with this list as the reason.
    """
    return sorted(
        app
        for app in set(_TELL_RE.findall(source))
        if not any((d / f"{app}.app").exists() for d in _APP_DIRS)
    )
