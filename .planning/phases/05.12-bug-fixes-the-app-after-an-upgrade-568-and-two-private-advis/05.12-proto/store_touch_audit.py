"""FIX-35 (#581) probe: does the default suite open a real store path today?

A pytest plugin. It adds a Python audit hook and reports every open, sqlite connect or
directory scan under the real home's app stores, with the test that did it. It changes
no test and no fixture.

Run from the repo root:
    PYTHONPATH=<this folder> uv run pytest -q -p store_touch_audit

Limit: a bare ``stat`` (``Path.exists``) raises no audit event, so it is not seen.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

_HOME = str(Path.home())
# The stores the package reads: Mail, Messages, Notes and Reminders (Group Containers),
# Photos prefs, the default file root, TCC.
_WATCHED = tuple(
    f"{_HOME}/{part}"
    for part in (
        "Library/Mail",
        "Library/Messages",
        "Library/Group Containers",
        "Library/Containers/com.apple.Photos",
        "Library/Application Support/com.apple.TCC",
        "Downloads",
        ".local/state/macos-apps-mcp",
    )
) + ("/Library/Application Support/com.apple.TCC",)
_EVENTS = {"open", "sqlite3.connect", "os.scandir", "os.listdir"}
_hits: Counter = Counter()


def _hook(event: str, args: tuple) -> None:
    if event not in _EVENTS or not args:
        return
    target = args[0]
    if isinstance(target, bytes):
        target = target.decode("utf-8", "replace")
    if not isinstance(target, str):
        return
    target = target.removeprefix("file:")
    if target.startswith(_WATCHED):
        test = os.environ.get("PYTEST_CURRENT_TEST", "(collection)").split(" ")[0]
        area = next(w for w in _WATCHED if target.startswith(w)).replace(_HOME, "~")
        _hits[(test, event, area)] += 1


def pytest_configure(config) -> None:
    sys.addaudithook(_hook)


def pytest_terminal_summary(terminalreporter) -> None:
    write = terminalreporter.write_line
    write(f"store-touch audit: {len(_hits)} (test, event, area) rows")
    for (test, event, area), n in sorted(_hits.items()):
        write(f"  {test} | {event} | {area} | {n}")
