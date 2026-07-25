"""Helper for test_gate_on_dispatch.py (#131) — run in a SUBPROCESS with
MACOS_APPS_ALLOW_SEND=mail already set, so importing macos_apps_mcp.server registers
send_mail/reply_all/forward_mail (read at import time — a normal test run never sets
this, so that dispatch path is otherwise never exercised).

Sends nothing real: the adapter's send/reply_all/forward methods are replaced with
recording stubs BEFORE the tool functions are invoked, so a call never reaches
osascript/Mail.app. Prints one JSON object to stdout: which tools registered, and
exactly what each tool forwarded to its adapter method — the parent test asserts on
both, so a transposed/dropped parameter fails loudly.
"""

from __future__ import annotations

import asyncio
import json

import macos_apps_mcp.server as srv

calls: dict[str, dict] = {}


def _record_send(
    to,
    subject="",
    body="",
    cc=None,
    bcc=None,
    html=False,
    from_address=None,
    dry_run=True,
):
    calls["send_mail"] = {
        "to": to,
        "subject": subject,
        "body": body,
        "cc": cc,
        "bcc": bcc,
        "html": html,
        "from_address": from_address,
        "dry_run": dry_run,
    }
    return {"sent": True}


def _record_reply_all(message_id, body, include_quote=True, dry_run=True):
    calls["reply_all"] = {
        "message_id": message_id,
        "body": body,
        "include_quote": include_quote,
        "dry_run": dry_run,
    }
    return {"sent": True}


def _record_forward(message_id, to, dry_run=True):
    calls["forward_mail"] = {"message_id": message_id, "to": to, "dry_run": dry_run}
    return {"sent": True}


# Instance-attribute assignment bypasses the class descriptor, so these are plain
# functions when called via `_mail.send(...)` — no `self` to account for.
srv._mail.send = _record_send
srv._mail.reply_all = _record_reply_all
srv._mail.forward = _record_forward

registered = {t.name for t in asyncio.run(srv.mcp.list_tools())}

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
srv.reply_all(
    "<msg-1@x>",
    "REPLY-BODY-VALUE",
    include_quote=False,
    dry_run=False,
)
srv.forward_mail("<msg-2@x>", "to2@example.com", dry_run=False)

print(json.dumps({"registered": sorted(registered), "calls": calls}))
