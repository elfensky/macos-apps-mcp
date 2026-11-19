"""One read for each adapter through the installed daemon. Reads only.

Queries match nothing where a query is possible. A read that needs a closed app
skips: its AppleScript would open the app on the owner's screen.
"""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("tool", "needs_app", "args"), READS, ids=[r[0] for r in READS]
)
def test_adapter_read_answers(guard, tool, needs_app, args):
    # pgrep on the Mac that owns the daemon: no TCC, no Apple Event.
    if needs_app and guard.on_device("pgrep", "-x", needs_app).returncode != 0:
        pytest.skip(f"{needs_app} is closed: this read would open the app")
    err, _data, text, secs = guard.run(tool, **args)
    assert not err, f"{tool} error secs={secs} {text[:200]}"
