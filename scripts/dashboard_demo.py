"""Serve the real dashboard on INVENTED data, for screenshots (docs/PROMOTION.md).

    uv run python scripts/dashboard_demo.py <empty-dir>

Seeds <empty-dir> as XDG_STATE_HOME with made-up writes (example.com addresses, a
calendar edit, a Mail batch with .eml backups, an undo preview, adapter toggles), then
serves the dashboard on http://127.0.0.1:47699 with a throwaway page key and prints the
URL that sets it. Nothing reads or writes the real audit log or backups.

Two traps:
* Do not click the Adapters switches: the adapters_off file sits at a fixed path in the
  real home folder (deploy._ADAPTERS_OFF_FILE), not under XDG_STATE_HOME.
* Keep Health and Backups out of screenshots: they show this Mac's paths and pids.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PORT = 47699
KEY = "Demo_page_key-0123456789abcdefABCDEFGHIJKL"  # throwaway, never the daemon's
CALLER = "claude-code 2.1"


def ptr(id_, summary, deeplink=""):
    return {"id": id_, "summary": summary, "deeplink": deeplink}


def write(ts, tool, op, args, *, dry_run=False, target=None, before=None, after=None):
    return {
        "ts": ts,
        "tool": tool,
        "op": op,
        "args": args,
        "dry_run": dry_run,
        "caller": CALLER,
        "target_id": target,
        "before": before,
        "after": after,
    }


def batch(backups, ts_plan, ts_done, rid, targets, args):
    """A recoverable Mail move as mail_recover logs it: plan, done, middleware line."""
    folder = backups / rid
    folder.mkdir(parents=True, exist_ok=True)
    for t in targets:
        (folder / f"{t['rowid']}.eml").write_text(
            f"From: {t['from']}\nTo: sam@example.com\nSubject: {t['subject']}\n"
            f"Message-ID: <{t['id']}>\n\nInvented message.\n" + "x" * 2400
        )
    plan = {
        "ts": ts_plan,
        "tool": "mail_recover",
        "op": "move",
        "phase": "plan",
        "receipt": rid,
        "destination": "Archive",
        "backup_dir": str(folder),
        "targets": [
            {
                "id": t["id"],
                "folder": "INBOX",
                "fidelity": "full",
                "rowid": t["rowid"],
                "backup": f"{folder}/{t['rowid']}.eml",
                "status": "planned",
            }
            for t in targets
        ],
    }
    done = {
        "ts": ts_done,
        "tool": "mail_recover",
        "op": "move",
        "phase": "done",
        "receipt": rid,
        "results": {t["id"]: "ok" for t in targets},
    }
    return [plan, done, write(ts_done, "move_mail", "move", args) | {"receipt": rid}]


def seed(root: Path) -> int:
    """Write the invented state under root/macos-apps-mcp; return the record count."""
    state = root / "macos-apps-mcp"
    news = [
        {
            "id": "weekly-1029@news.example.com",
            "rowid": 4101,
            "subject": "This week in design",
            "from": "The Weekly <hello@news.example.com>",
        },
        {
            "id": "digest-77@updates.example.org",
            "rowid": 4102,
            "subject": "Your October digest",
            "from": "Updates <digest@updates.example.org>",
        },
        {
            "id": "promo-2210@shop.example.net",
            "rowid": 4103,
            "subject": "Autumn sale ends Sunday",
            "from": "Shop <deals@shop.example.net>",
        },
    ]
    ids = ",".join(t["id"] for t in news)
    move = {"ids": ids, "from_mailbox": "INBOX", "to_mailbox": "Archive"}
    rid = "20261024-091204-118204-001-move"
    records = [
        write(
            "2026-10-24T08:52:10",
            "create_reminder",
            "create",
            {"title": "Renew passport", "due": "2026-11-03"},
            after=ptr("R-71C2", "Renew passport — due Mon 3 Nov"),
        ),
        write(
            "2026-10-24T09:05:41",
            "update_event",
            "update",
            {
                "id": "E-4F10",
                "title": "Team sync",
                "start": "2026-10-30T11:00",
                "end": "2026-10-30T11:30",
            },
            target="E-4F10",
            before=ptr(
                "E-4F10", "Team sync — Thu 30 Oct 10:00–10:30", "calshow:783507600"
            ),
            after=ptr(
                "E-4F10", "Team sync — Thu 30 Oct 11:00–11:30", "calshow:783511200"
            ),
        ),
        write("2026-10-24T09:11:58", "move_mail", "move", move, dry_run=True),
        *batch(
            state / "backup" / "mail",
            "2026-10-24T09:12:04",
            "2026-10-24T09:12:06",
            rid,
            news,
            move,
        ),
        write(
            "2026-10-24T10:30:15",
            "update_note",
            "update",
            {"id": "N-118", "body": "Packing list: passport, charger, rain jacket"},
            dry_run=True,
            target="N-118",
            before=ptr("N-118", "Packing list: passport, charger"),
        ),
        write(
            "2026-10-24T14:02:33",
            "complete_reminder",
            "complete",
            {"id": "R-55A0"},
            target="R-55A0",
            before=ptr("R-55A0", "Book dentist — due Fri 24 Oct"),
        ),
        write(
            "2026-10-24T16:45:09",
            "send_mail",
            "send",
            {"to": "alex@example.com", "subject": "Slides for Thursday"},
            dry_run=True,
        ),
        write(
            "2026-10-25T09:20:47", "mail_undo", "undo", {"receipt": rid}, dry_run=True
        ),
        *(
            {
                "ts": f"2026-10-25T09:24:{30 + i}",
                "tool": "dashboard",
                "op": "toggle",
                "args": {"adapter": a, "on": False},
                "dry_run": False,
                "caller": "dashboard",
                "target_id": a,
                "before": None,
                "after": None,
            }
            for i, a in enumerate(("photos", "music"))
        ),
    ]
    usage = {
        "events": 41,
        "mail_search": 37,
        "reminders": 29,
        "mail_needs_response": 18,
        "free_busy": 14,
        "notes": 12,
        "mail_body": 11,
        "doctor": 6,
        "move_mail": 4,
    }
    state.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    (state / "audit.jsonl").write_text("\n".join(lines) + "\n")
    calls = [
        json.dumps({"ts": f"2026-10-{20 + i % 5:02d}T09:{i % 60:02d}:00", "tool": t})
        for t, n in usage.items()
        for i in range(n)
    ]
    (state / "usage.jsonl").write_text("\n".join(calls) + "\n")
    return len(records)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1]).expanduser().resolve()
    real = (Path.home() / ".local" / "state").resolve()
    if root == real or real in root.parents or (root.exists() and any(root.iterdir())):
        sys.exit(f"refusing {root}: give an EMPTY folder outside {real}")
    os.environ["XDG_STATE_HOME"] = str(root)  # before any macos_apps_mcp import
    assert seed(root) == 12

    import uvicorn

    from macos_apps_mcp import dashboard
    from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS

    print(f"open http://127.0.0.1:{PORT}/key?k={KEY}", flush=True)
    app = dashboard.build_app(port=PORT, token="demo", key=KEY)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
