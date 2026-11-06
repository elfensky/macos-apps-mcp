"""One read for each adapter through the installed daemon. Reads only.

Queries match nothing where a query is possible. A read that needs a closed app
skips: its AppleScript would open the app on the owner's screen.
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.device

NONE = "zz-macos-apps-mcp-no-such-item"
DAY = "2027-03-20"

READS = [
    ("ping", None, {}),
    ("now", None, {}),
    ("calendars", None, {}),
    ("events", None, {"when": DAY}),
    ("free_busy", None, {"start": f"{DAY}T09:00:00", "end": f"{DAY}T17:00:00"}),
    ("reminder_lists", None, {}),
    ("mail_search", None, {"subject": NONE}),
    ("mail_overview", "Mail", {}),
    ("mail_stats", None, {"days": 7}),
    ("messages_search", None, {"query": NONE}),
    ("messages_chats", "Messages", {}),
    ("notes", None, {"title": NONE}),
    ("photos", None, {"query": NONE}),
    ("contacts", "Contacts", {"name": NONE}),
    ("music_search", "Music", {"query": NONE}),
    ("safari_tabs", "Safari", {}),
    ("shortcuts", None, {"name": NONE}),
]


def _running(app: str) -> bool:
    """pgrep only: no TCC, no Apple Event."""
    return subprocess.run(["pgrep", "-x", app], capture_output=True).returncode == 0


@pytest.mark.parametrize(
    ("tool", "needs_app", "args"), READS, ids=[r[0] for r in READS]
)
def test_adapter_read_answers(guard, tool, needs_app, args):
    if needs_app and not _running(needs_app):
        pytest.skip(f"{needs_app} is closed: this read would open the app")
    err, _data, text, secs = guard.run(tool, **args)
    assert not err, f"{tool} error secs={secs} {text[:200]}"
