"""#131: exercise the tool→adapter dispatch path for send_mail/reply_all/forward_mail.

Registration is the only thing that truly needs the import-time gate on — that one
check runs in a subprocess with MACOS_APPS_ALLOW_SEND=mail. The dispatch itself does
NOT: a gate-off `_send_tool` returns the plain function undecorated (and FastMCP's
`mcp.tool()(fn)` returns the plain function even gate-on), so `srv.send_mail` is
callable in-process — the three forwarding tests below patch the adapter with
recording fakes and call the tools directly. Nothing real ever sends.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import macos_apps_mcp.server as srv


def test_gate_on_registers_the_three_send_tools():
    # The one true import-time-gate assertion: with ALLOW_SEND=mail set BEFORE import,
    # the three outbound tools register. Everything else about them tests in-process.
    code = (
        "import asyncio, json, macos_apps_mcp.server as srv; "
        "print(json.dumps(sorted(t.name for t in asyncio.run(srv.mcp.list_tools()))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ["HOME"],
            "MACOS_APPS_ALLOW_SEND": "mail",
        },
    )
    assert out.returncode == 0, out.stderr
    registered = set(json.loads(out.stdout.strip().splitlines()[-1]))
    assert {"send_mail", "reply_all", "forward_mail"} <= registered


def test_send_mail_forwards_every_argument_to_the_adapter(monkeypatch):
    calls = {}

    def record(to, subject, body, *, cc, bcc, html, from_address, dry_run):
        calls.update(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            from_address=from_address,
            dry_run=dry_run,
        )
        return {"sent": True}

    monkeypatch.setattr(srv._mail, "send", record)
    srv.send_mail(
        "to@example.com",
        subject="SUBJECT-VALUE",
        body="BODY-VALUE",
        cc="cc@example.com",
        bcc="bcc@example.com",
        html=True,
        from_address="from@example.com",
        dry_run=False,
    )
    assert calls == {
        "to": "to@example.com",
        "subject": "SUBJECT-VALUE",
        "body": "BODY-VALUE",
        "cc": "cc@example.com",
        "bcc": "bcc@example.com",
        "html": True,
        "from_address": "from@example.com",
        "dry_run": False,
    }


def test_reply_all_forwards_every_argument_to_the_adapter(monkeypatch):
    calls = {}

    def record(message_id, body, include_quote, *, dry_run):
        calls.update(
            message_id=message_id,
            body=body,
            include_quote=include_quote,
            dry_run=dry_run,
        )
        return {"sent": True}

    monkeypatch.setattr(srv._mail, "reply_all", record)
    srv.reply_all("<msg-1@x>", "REPLY-BODY-VALUE", include_quote=False, dry_run=False)
    assert calls == {
        "message_id": "<msg-1@x>",
        "body": "REPLY-BODY-VALUE",
        "include_quote": False,
        "dry_run": False,
    }


def test_forward_mail_forwards_every_argument_to_the_adapter(monkeypatch):
    calls = {}

    def record(message_id, to, *, dry_run):
        calls.update(message_id=message_id, to=to, dry_run=dry_run)
        return {"sent": True}

    monkeypatch.setattr(srv._mail, "forward", record)
    srv.forward_mail("<msg-2@x>", "to2@example.com", dry_run=False)
    assert calls == {
        "message_id": "<msg-2@x>",
        "to": "to2@example.com",
        "dry_run": False,
    }
