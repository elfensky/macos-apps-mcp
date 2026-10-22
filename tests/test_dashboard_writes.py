"""The write list and the detail of one write (PLAT-02, D-11, D-12, D-13).

Same harness as the other dashboard tests: ``tests/_dashboard.py`` builds the app with
the test page key and sends its cookie; there is no socket. Every fixture is invented
(the sketch data style) and written under a private ``XDG_STATE_HOME``, so no test
reads or writes the developer's real audit log or backups.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import date

import pytest

from macos_apps_mcp import audit, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from macos_apps_mcp.adapters import mail_recover
from macos_apps_mcp.dashboard import writes
from macos_apps_mcp.errors import NativeError
from tests._dashboard import get

TS = "2026-09-28T09:31:55"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """A private state dir: the audit log and the backup tree live under it."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    return tmp_path


def put(*records, name="audit.jsonl"):
    """Append invented records to the audit log (or its rotated twin)."""
    with (audit.state_dir() / name).open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def update(ts=TS, **kw):
    return {
        "ts": ts,
        "tool": "update_event",
        "op": "update",
        "args": {"id": "E-1", "start": "2026-09-30T15:00"},
        "dry_run": False,
        "caller": "claude-code 2.1",
        "target_id": "E-1",
        "before": {
            "id": "E-1",
            "summary": "Dentist — Tue 30 Sep 14:00–14:30",
            "deeplink": "calshow:780000000",
        },
        "after": {
            "id": "E-1",
            "summary": "Dentist — Tue 30 Sep 15:00–15:30",
            "deeplink": "calshow:780003600",
        },
        **kw,
    }


def legacy_trash(ts="2026-09-28T09:40:12"):
    """A pre-#222 record: no ``dry_run``, no ``caller``."""
    return {
        "ts": ts,
        "tool": "trash_mail",
        "op": "trash",
        "args": {"ids": "a@x.invalid,b@x.invalid", "mailbox": "INBOX"},
        "target_id": None,
        "before": None,
        "after": None,
    }


def page(path):
    r = get(path)
    assert r.status_code == 200, (path, r.status_code)
    return r.text


def plain(text):
    return html.unescape(text)


def test_the_list_shows_a_write_as_one_row():
    put(update())
    text = page("/")
    assert f'href="/write/{TS}/0"' in text
    assert ">Updated Dentist — Tue 30 Sep 15:00–15:30<" in text
    assert '<span class="mono">update_event</span>' in text
    assert '<span class="chip destructive">changes</span>' in text
    assert "09:31" in text


def test_detail_word_diff_resolved_dry_run_and_raw_line():
    put(update())
    assert "update_event" not in registry.dry_run_defaults()
    text = page(f"/write/{TS}/0")
    assert '<del class="w">14:00–14:30</del>' in text
    assert '<ins class="w">15:00–15:30</ins>' in text
    assert "<dt>dry_run</dt>" in text and "not passed — not a dry-run tool" in text
    assert '<details class="raw">' in text and "1 line in audit.jsonl" in text
    assert "Preview only" not in text
    assert 'href="calshow:780003600"' in text
    assert 'data-copy="E-1"' in text
    assert "<dt>caller</dt><dd>claude-code 2.1</dd>" in text


def test_preview_a_legacy_record_reads_as_a_preview_not_a_write():
    assert registry.dry_run_defaults()["trash_mail"] is True
    put(legacy_trash())
    listing = page("/")
    assert 'class="row clickable preview"' in listing
    assert '<span class="chip">preview</span>' in listing
    text = page("/write/2026-09-28T09:40:12/0")
    assert "Preview only — nothing changed." in text
    assert "defaults to a preview" in text and "trash_mail" in text
    assert "not passed — defaulted to true" in text
    assert "What it would have changed" in text
    assert "<dt>caller</dt>" not in text


def test_ordinal_counts_rows_sharing_a_timestamp_and_bad_ones_are_404():
    put(update(), update(tool="delete_event", op="delete", after=None))
    first, second = page(f"/write/{TS}/0"), page(f"/write/{TS}/1")
    assert "Updated Dentist" in first and "Deleted Dentist" in second
    assert get(f"/write/{TS}/2").status_code == 404
    assert get("/write/not-a-time/0").status_code == 404
    assert get(f"/write/{TS}/-1").status_code == 404


def test_escape_every_audit_string_and_the_deeplink_scheme():
    hostile = '"><script>alert(1)</script>'
    put(
        update(
            args={"note": '" onmouseover="x', "html": hostile},
            target_id=hostile,
            before=None,
            after={
                "id": "E-1",
                "summary": "<script>alert(1)</script>",
                "deeplink": "javascript:alert(1)",
            },
        ),
        update(
            ts="2026-09-28T09:32:00",
            tool="<img src=x onerror=alert(1)>",
            caller="<b>evil</b>",
            after={"id": "x", "summary": "ok", "deeplink": "data:text/html,<p>"},
        ),
    )
    for path in ("/", f"/write/{TS}/0", "/write/2026-09-28T09:32:00/0"):
        text = page(path)
        assert "<script>alert" not in text and "<img src=x" not in text
        assert "<b>evil</b>" not in text and 'onmouseover="x' not in text
        assert not re.search(r'href="(javascript|data|vbscript|file):', text)
    detail = page(f"/write/{TS}/0")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
    assert "&quot; onmouseover=&quot;x" in detail
    assert "Open in" not in detail  # the unsafe deeplink gives no link at all


# --- batches (D-12, D-13) -------------------------------------------------------

RID = "20260928-094010-123456-001-move"
IDS = ("a1@x.invalid", "b2@x.invalid")


def backup_root():
    return audit.state_dir() / "backup" / "mail"


def batch(*, rid=RID, op="move", ids=IDS, mw=True, mw_receipt=False, files=True, **kw):
    """A plan + done pair (+ the middleware line), written like ``recoverable`` does.
    Target 1 has its ``.eml`` on disk (3 KB); target 2 was never written."""
    folder = backup_root() / rid
    if files:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "101.eml").write_bytes(b"x" * 3072)
    plan = {
        "ts": "2026-09-28T09:40:10",
        "tool": "mail_recover",
        "op": op,
        "phase": "plan",
        "receipt": rid,
        "destination": "Trash",
        "backup_dir": str(folder),
        "targets": [
            {
                "id": ids[0],
                "folder": "INBOX",
                "fidelity": "full",
                "rowid": 101,
                "backup": f"{folder}/101.eml",
                "status": "planned",
            },
            {
                "id": ids[1],
                "folder": "INBOX",
                "fidelity": "partial",
                "rowid": 102,
                "backup": f"{folder}/102.eml",
                "status": "planned",
            },
        ],
    }
    done = {
        "ts": "2026-09-28T09:40:12",
        "tool": "mail_recover",
        "op": op,
        "phase": "done",
        "receipt": rid,
        "results": {ids[0]: "ok", ids[1]: "not-in-source"},
    }
    records = [{**plan, **kw.get("plan", {})}, {**done, **kw.get("done", {})}]
    if mw:
        records.append(
            {
                "ts": "2026-09-28T09:40:12",
                "tool": "move_mail",
                "op": "move",
                "args": {"ids": ",".join(ids), "to_mailbox": "Trash"},
                "dry_run": False,
                "caller": "claude-code 2.1",
                "target_id": None,
                "before": None,
                "after": None,
                **({"receipt": rid} if mw_receipt else {}),
            }
        )
    put(*records)
    return records


def rows_in(text):
    return re.findall(r'<a class="row clickable[^"]*" href="([^"]+)"', text)


def test_batch_plan_done_and_move_read_as_one_row():
    batch()
    listing = page("/")
    assert rows_in(listing) == ["/write/2026-09-28T09:40:12/0"]
    assert ">Moved 2 messages to Trash<" in listing
    assert '<span class="mono">move_mail</span> · receipt' in listing


def test_batch_detail_shows_each_message_its_backup_and_outcome():
    batch()
    text = page("/write/2026-09-28T09:40:12/0")
    assert "<b>1 of 2</b>" in text
    assert "101.eml · 3 KB" in text and "no file" in text
    assert 'class="chip fid full"' in text and 'class="chip fid partial"' in text
    assert text.count('class="left-out"') == 1  # only the message that did not move
    assert "missing when the batch ran, so it never moved" in text
    assert f'data-copy="{backup_root() / RID}"' in text
    assert "3 lines in audit.jsonl" in text
    assert IDS[0] in text and IDS[1] in text


def move_line(ts, **kw):
    return {
        "ts": ts,
        "tool": "move_mail",
        "op": "move",
        "args": {"ids": "a"},
        "dry_run": False,
        "target_id": None,
        "before": None,
        "after": None,
        **kw,
    }


def test_the_receipt_key_links_exactly_and_beats_adjacency():
    batch(mw=False)
    # an unrelated write sits between the done record and the middleware line
    put(update(ts="2026-09-28T09:40:12", args={"id": "E-2"}))
    put(move_line("2026-09-28T09:40:13", receipt=RID))
    assert len(rows_in(page("/"))) == 2  # the batch and the stray write
    put(move_line("2026-09-28T09:40:14"))  # no receipt key and not adjacent
    assert len(rows_in(page("/"))) == 3


def test_a_plan_without_a_done_record_leaves_every_outcome_unknown():
    batch(mw=False)
    log = audit.state_dir() / "audit.jsonl"
    log.write_text(log.read_text().splitlines()[0] + "\n")  # the plan alone
    text = page("/write/2026-09-28T09:40:10/0")
    assert "<b>0 of 2</b>" in text and "may or may not have moved" in text


def test_undo_prompt_only_when_the_plan_resolves(monkeypatch):
    batch()
    path = "/write/2026-09-28T09:40:12/0"
    text = page(path)
    assert "To undo, ask Claude" in text
    assert f'data-copy="Undo mail receipt {RID}"' in text
    assert f'mail_undo(receipt="{RID}", dry_run=false)' in plain(text)
    assert "<details" in text and "Exact tool call" in text

    def rotated(rid):
        raise NativeError(f"no recoverable-mail receipt {rid!r}")

    monkeypatch.setattr(mail_recover, "find_receipt", rotated)
    text = page(path)
    assert "To undo, ask Claude" not in text and "Undo mail receipt" not in text
    assert "rotated out of the recent audit log" in text
    assert "The backup files remain." in text


def test_dedupe_cli_batch_without_a_middleware_line_is_a_batch_row():
    batch(rid="20260928-094010-123456-002-dedupe", op="dedupe", mw=False)
    listing = page("/")
    assert len(rows_in(listing)) == 1
    assert '<span class="mono">dedupe-mail</span> · receipt' in listing
    assert "Deduplicated" in page("/write/2026-09-28T09:40:10/0")


def undo_line(**kw):
    return {
        "ts": "2026-09-28T10:25:40",
        "tool": "mail_undo",
        "op": "undo",
        "args": {"receipt": RID, "dry_run": False},
        "dry_run": False,
        "caller": "claude-code 2.1",
        "target_id": None,
        "before": None,
        "after": None,
        **kw,
    }


def test_a_later_undo_marks_the_batch_undone_and_the_undo_links_back():
    batch()
    put(undo_line())
    text = page("/write/2026-09-28T09:40:12/0")
    assert "Undone" in text and "by claude-code 2.1" in text
    assert "To undo, ask Claude" not in text
    mine = page("/write/2026-09-28T10:25:40/0")
    assert (
        "This undo moved the messages of an earlier batch back to where they "
        "came from." in mine
    )
    assert 'href="/write/2026-09-28T09:40:12/0"' in mine


def test_an_undo_without_a_caller_names_none():
    batch()
    put(undo_line(caller=None))
    text = page("/write/2026-09-28T09:40:12/0")
    assert "Undone" in text and " by " not in text.split("Undone", 1)[1][:60]


def test_a_preview_undo_does_not_mark_the_batch_undone():
    batch()
    put(undo_line(dry_run=True))
    text = page("/write/2026-09-28T09:40:12/0")
    assert "Undone" not in text and "To undo, ask Claude" in text


def test_a_plain_write_says_it_has_no_backup():
    put(update())
    assert "No backup for this write." in page(f"/write/{TS}/0")


def test_receipt_path_tricks_never_reach_the_filesystem(monkeypatch, tmp_path):
    decoy = audit.state_dir() / "etc"  # backup/mail/../../etc is this folder
    decoy.mkdir(parents=True)
    (decoy / "101.eml").write_bytes(b"secret")
    batch(rid="../../etc", files=False, plan={"backup_dir": "../../etc"}, mw=False)
    # a well-formed receipt whose folder is a symlink out of the backup root
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "101.eml").write_bytes(b"y" * 100)
    backup_root().mkdir(parents=True)
    (backup_root() / RID).symlink_to(outside)
    batch(files=False, mw=False)
    for name in ("_backup_dir", "purge_backup", "backup_usage"):
        monkeypatch.setattr(
            mail_recover, name, lambda *a, **k: pytest.fail("a write helper ran")
        )
    text = page("/write/2026-09-28T09:40:10/0") + page("/write/2026-09-28T09:40:10/1")
    assert "101.eml ·" not in text and text.count("no file") >= 4


def test_rendering_never_creates_the_backup_tree():
    batch(files=False)
    assert not (audit.state_dir() / "backup").exists()
    page("/")
    page("/write/2026-09-28T09:40:12/0")
    assert not (audit.state_dir() / "backup").exists()


def test_escape_batch_fields():
    hostile = '"><script>alert(1)</script>'
    batch(ids=(hostile, "b@x.invalid"), plan={"destination": hostile})
    for path in ("/", "/write/2026-09-28T09:40:12/0"):
        assert "<script>alert" not in page(path)
    assert "&lt;script&gt;" in page("/write/2026-09-28T09:40:12/0")


# --- finding a write (D-11) -----------------------------------------------------


def reminder(ts="2026-09-28T11:00:00", summary="Pick up the café order"):
    return {
        "ts": ts,
        "tool": "create_reminder",
        "op": "create",
        "args": {"title": summary},
        "dry_run": False,
        "caller": "claude-code 2.1",
        "target_id": "R-1",
        "before": None,
        "after": {"id": "R-1", "summary": summary, "deeplink": ""},
    }


def sent(ts="2026-09-28T12:00:00"):
    return {
        "ts": ts,
        "tool": "send_mail",
        "op": "send",
        "args": {"to": "someone@x.invalid", "dry_run": False},
        "dry_run": False,
        "caller": "claude-code 2.1",
        "target_id": None,
        "before": None,
        "after": {"id": "M-1", "summary": "Sent: hello", "deeplink": ""},
    }


def titles(text):
    return re.findall(r'<div class="title">([^<]*)</div>', text)


def test_the_search_form_carries_its_state():
    put(update())
    text = page("/?q=dent&filter=receipt&previews=0")
    assert '<form class="search" method="get" action="/">' in text
    assert 'name="q"' in text and 'placeholder="Filter"' in text
    assert '<input type="hidden" name="previews" value="0">' in text
    assert '<input type="hidden" name="filter" value="receipt">' in text
    assert 'value="dent"' in text and 'value="1" checked' not in text


def test_search_matches_words_ids_and_folds_case_and_diacritics():
    put(update(), reminder())
    batch()
    assert titles(page("/?q=dentist")) == ["Updated Dentist — Tue 30 Sep 15:00–15:30"]
    assert titles(page("/?q=CAFE")) == ["Created Pick up the café order"]  # fold_text
    assert titles(page("/?q=b2@x")) == ["Moved 2 messages to Trash"]  # a target id
    assert titles(page("/?q=094010-123456")) == ["Moved 2 messages to Trash"]  # receipt
    assert titles(page("/?q=claude-code+dentist"))[0].startswith("Updated Dentist")
    assert titles(page("/?q=nothing-like-this")) == []


def test_previews_are_shown_by_default_and_the_switch_hides_them():
    put(update(), legacy_trash())
    assert len(rows_in(page("/"))) == 2
    assert len(rows_in(page("/?previews=0"))) == 1
    assert len(rows_in(page("/?previews=0&previews=1"))) == 2  # hidden + checked box
    assert 'value="1" checked' in page("/")
    assert 'value="1" checked' not in page("/?previews=0")


def test_filter_narrows_to_batches_outbound_or_one_app():
    put(update(), sent())
    batch()
    assert len(rows_in(page("/?filter=receipt"))) == 1
    assert titles(page("/?filter=outbound")) == ["Sent Sent: hello"]
    mail = titles(page("/?filter=app:mail"))
    assert sorted(mail) == ["Moved 2 messages to Trash", "Sent Sent: hello"]
    assert len(rows_in(page("/?filter=app:calendar"))) == 1
    assert len(rows_in(page("/?filter=app:nonesuch"))) == 3  # unknown acts as all
    assert len(rows_in(page("/?filter=bogus"))) == 3


def test_sidebar_counts_leave_out_previews_and_list_apps_alphabetically():
    put(update(), legacy_trash(), sent())
    batch()
    text = page("/")
    assert 'All writes<span class="count">3</span>' in text
    assert 'Batches with receipts<span class="count">1</span>' in text
    assert 'Sent off this Mac<span class="count">1</span>' in text
    assert 'href="/?filter=app:calendar"' in text and 'href="/?filter=app:mail"' in text
    assert text.index("app:calendar") < text.index("app:mail")
    assert 'Mail<span class="count">2</span>' in text
    assert '<a class="nav-item active" href="/?filter=receipt"' in page(
        "/?filter=receipt"
    )


def test_day_headers_read_today_yesterday_then_a_dated_header(monkeypatch):
    monkeypatch.setattr(writes, "_today", lambda: date(2026, 9, 28))
    put(
        update(ts="2026-09-28T09:00:00"),
        update(ts="2026-09-27T09:00:00"),
        update(ts="2026-09-22T09:00:00"),
    )
    headers = re.findall(r'<div class="day">([^<]*)</div>', page("/"))
    # 22 Sep 2026 is a Tuesday (the plan's "Mon 22 Sep" example was a 2025 date)
    assert headers == ["Today", "Yesterday", "Tue 22 Sep"]


def test_empty_states():
    text = page("/")
    assert "Select a write" in text and "No writes recorded yet" in text
    put(update())
    text = page("/?q=zzz")
    assert "No writes match" in text and rows_in(text) == []
    assert "Select a write" in text


def test_an_unreadable_log_is_a_banner_never_an_empty_list():
    (audit.state_dir() / "audit.jsonl").mkdir()  # reading a directory fails
    text = page("/")
    assert '<div class="banner bad">' in text and "audit log unreadable" in text
    assert rows_in(text) == [] and "No writes recorded yet" not in text


def test_links_keep_the_query_and_the_open_row_is_selected_with_a_back_link():
    put(update(), reminder())
    text = page(f"/write/{TS}/0?q=dentist&previews=0")
    assert f'href="/write/{TS}/0?q=dentist&amp;previews=0"' in text
    assert 'class="row clickable selected"' in text
    assert re.search(
        r'<a class="btn link b-back" href="/\?q=dentist&amp;previews=0">', text
    )
    assert "‹ Back" in text


def test_a_large_log_renders_fast():
    lines = [
        update(ts=f"2026-09-{1 + i % 27:02d}T{i % 24:02d}:{i % 60:02d}:00")
        for i in range(3000)
    ]
    put(*lines)
    started = time.perf_counter()
    text = page("/")
    assert time.perf_counter() - started < 3
    assert len(rows_in(text)) == 3000


def test_dashboard_records_render_truthfully():
    base = {
        "tool": "dashboard",
        "dry_run": False,
        "caller": "dashboard",
        "before": None,
        "after": None,
    }
    put(
        {**base, "ts": "2026-09-28T08:00:00", "op": "toggle", "target_id": "mail",
         "args": {"adapter": "mail", "on": False}},
        {**base, "ts": "2026-09-28T08:01:00", "op": "discard", "target_id": None,
         "args": {"adapters_off": ["photos"]}},
        {**base, "ts": "2026-09-28T08:02:00", "op": "restart", "target_id": None,
         "args": {}},
        {**base, "ts": "2026-09-28T08:03:00", "op": "toggle", "target_id": "<b>x</b>",
         "args": {"adapter": "<b>x</b>", "on": True}},
    )  # fmt: skip
    listing = page("/")
    assert {
        "Turned Mail off",
        "Discarded pending adapter changes",
        "Restarted the daemon",
        "Turned &lt;b&gt;x&lt;/b&gt; on",
    } <= set(titles(listing))
    assert "<b>x</b>" not in listing and "<b>X</b>" not in listing
    for ts in ("08:00:00", "08:01:00", "08:02:00", "08:03:00"):
        text = page(f"/write/2026-09-28T{ts}/0")
        assert "<dd>dashboard</dd>" in text  # the caller
        for absent in (
            "To undo, ask Claude",
            "No backup for this write.",
            "Preview only",
            "<del",
            "<ins",
            "Open in",
        ):
            assert absent not in text
        assert "<b>x</b>" not in text and "<b>X</b>" not in text
    assert "Turned Mail off" in page("/write/2026-09-28T08:00:00/0")
