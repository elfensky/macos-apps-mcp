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

import pytest

from macos_apps_mcp import audit, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
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
