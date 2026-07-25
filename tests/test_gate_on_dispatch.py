"""#131: exercise the gate-ON tool→adapter dispatch path for send_mail/reply_all/
forward_mail.

MACOS_APPS_ALLOW_SEND is read at import time (server._allow_send), so a normal test
run never sets it and these three tools never register — meaning their dispatch
(send_mail alone hand-forwards 8 parameters) is otherwise completely untested. This
runs the check in a SUBPROCESS with the gate on, via _gate_on_dispatch_check.py,
which monkeypatches the adapter's send/reply_all/forward methods with recording
stubs before calling the tool functions — so nothing real ever sends. See that file
for the exact values exercised.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).with_name("_gate_on_dispatch_check.py")


@pytest.fixture(scope="module")
def gate_on_result() -> dict:
    """Run the subprocess check ONCE per module — every test below asserts on a
    different slice of the same recorded run, so there's no need to re-spawn a fresh
    interpreter (and re-import the whole server) per assertion."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ["HOME"],
        "MACOS_APPS_ALLOW_SEND": "mail",
    }
    out = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_gate_on_registers_the_three_send_tools(gate_on_result):
    assert {"send_mail", "reply_all", "forward_mail"} <= set(
        gate_on_result["registered"]
    )


def test_send_mail_forwards_every_argument_to_the_adapter(gate_on_result):
    assert gate_on_result["calls"]["send_mail"] == {
        "to": "to@example.com",
        "subject": "SUBJECT-VALUE",
        "body": "BODY-VALUE",
        "cc": "cc@example.com",
        "bcc": "bcc@example.com",
        "html": True,
        "from_address": "from@example.com",
        "dry_run": False,
    }


def test_reply_all_forwards_every_argument_to_the_adapter(gate_on_result):
    assert gate_on_result["calls"]["reply_all"] == {
        "message_id": "<msg-1@x>",
        "body": "REPLY-BODY-VALUE",
        "include_quote": False,
        "dry_run": False,
    }


def test_forward_mail_forwards_every_argument_to_the_adapter(gate_on_result):
    assert gate_on_result["calls"]["forward_mail"] == {
        "message_id": "<msg-2@x>",
        "to": "to2@example.com",
        "dry_run": False,
    }
