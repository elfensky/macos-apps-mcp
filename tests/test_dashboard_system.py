"""The Health and Backups pages (PLAT-02, D-13, D-14, RESEARCH C7).

Same harness as the other dashboard tests: ``tests/_dashboard.py`` builds the app with
the test page key and sends its cookie; there is no socket. ``doctor.diagnose`` and
``deploy.grant_report`` are faked at the seam, so no test reads the real TCC database,
sends an Apple Event or starts an EventKit request. Every fixture is invented and
written under a private ``XDG_STATE_HOME``.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from pathlib import Path

import pytest

from macos_apps_mcp import audit, dashboard, deploy, doctor, registry
from macos_apps_mcp import server as _server  # noqa: F401 — fills registry.TOOLS
from macos_apps_mcp.adapters import mail_addressing, mail_recover
from macos_apps_mcp.dashboard import grants, health, recovery
from tests._dashboard import get

BUNDLE = deploy.BUNDLE_ID
BOTH_READ = {"user": None, "system": None}


def _identity(service, target=None, granted=True):
    row = {"client": BUNDLE, "granted": granted}
    if target:
        row["target"] = target
    return service, row


def make_ids(*, fda=True, skip=("music",), denied=()):
    """A TCC identity map for ``BUNDLE``: every Automation target granted except the
    adapters in ``skip`` (no row at all), Calendar and Reminders granted, the Full Disk
    Access row ``fda``. ``denied`` names adapters whose AppleEvents row is denied."""
    ids: dict[str, list[dict]] = {}
    pairs = [
        ("kTCCServiceCalendar", None, True),
        ("kTCCServiceReminders", None, True),
        ("kTCCServiceSystemPolicyAllFiles", None, fda),
    ]
    for adapter, needs in grants.ADAPTER_GRANTS.items():
        for service, target in needs:
            if target and adapter not in skip:
                pairs.append((service, target, adapter not in denied))
    for service, target, granted in pairs:
        s, row = _identity(service, target, granted)
        ids.setdefault(s, []).append(row)
    return ids


def make_report(ids="default", **surface_overrides):
    ids = make_ids() if ids == "default" else ids
    surfaces = {
        "calendar": ("eventkit", True, "full_access"),
        "reminders": ("eventkit", True, "full_access"),
        "full_disk_access": ("fda", True, "ok"),
    }
    surfaces.update(surface_overrides)
    return {
        "version": "0.15.0",
        "build": "abc1234 2026-10-21T10:00:00Z",
        "summary": "no denied surfaces; Automation unprobed",
        "surfaces": [
            {"surface": n, "kind": k, "ok": ok, "status": st}
            for n, (k, ok, st) in surfaces.items()
        ],
        "deployment": {
            "mode": "daemon",
            "agent": "enabled",
            "grant_identities": ids,
            "mail_backups": "3.4 MB in 12 receipts (oldest 20260801), kept forever",
            "note": "grants listed per identity",
        },
    }


class Doc:
    """The fake ``doctor.diagnose``: records its calls, can block on ``gate``."""

    def __init__(self):
        self.calls: list = []
        self.report = make_report()
        self.reasons = dict(BOTH_READ)
        self.gate: threading.Event | None = None

    def diagnose(self, request=False):
        self.calls.append(request)
        if self.gate is not None:
            assert self.gate.wait(10), "the test never released the fake"
        return self.report

    def grant_report(self):
        return {
            "identities": self.report["deployment"]["grant_identities"],
            "reasons": self.reasons,
        }


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """A private state dir and a fresh single-flight lock; the daemon role."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.setattr(health, "_lock", threading.Lock())
    monkeypatch.setattr(health, "_last", None)
    monkeypatch.setattr(health, "_dot", None)
    return tmp_path


@pytest.fixture
def doc(monkeypatch):
    d = Doc()
    monkeypatch.setattr(doctor, "diagnose", d.diagnose)
    monkeypatch.setattr(deploy, "grant_report", d.grant_report)
    return d


def titles(text):
    return re.findall(r'<div class="title">(.*?)</div>', text)


def sub_of(text, title):
    m = re.search(
        rf'<div class="title">{re.escape(title)}</div><div class="sub">(.*?)</div>',
        text,
        re.S,
    )
    return html.unescape(m.group(1)) if m else None


def value_of(text, title):
    m = re.search(
        rf'<div class="title">{re.escape(title)}</div></div>'
        r'<span class="muted">(.*?)</span>',
        text,
        re.S,
    )
    return html.unescape(m.group(1)) if m else None


# --- Health: the doctor report (D-14) ---------------------------------------------


def test_health_shows_what_doctor_reports(doc):
    doc.report["summary"] = "<script>alert(1)</script>"
    r = get("/health")
    assert r.status_code == 200
    text = r.text
    assert "<h1>Health</h1>" in text
    assert 'What <span class="mono">doctor</span> reports right now.' in text
    for t in ("Daemon", "Adapters", "Full Disk Access", "EventKit", "Outbound"):
        assert f'<div class="title">{t}</div>' in text
    assert "Mail backups" in titles(text)
    assert sub_of(text, "Mail backups").startswith("3.4 MB in 12 receipts")
    assert "Deployment" in text
    assert value_of(text, "Version") == "0.15.0 · built abc1234 2026-10-21T10:00:00Z"
    assert re.fullmatch(r"daemon, pid \d+, up .+", value_of(text, "Mode"))
    assert value_of(text, "Listens on") == "127.0.0.1:47632 (loopback only)"
    assert value_of(text, "Grant identity") == BUNDLE
    # the full report is escaped JSON inside <details>
    m = re.search(
        r"<details[^>]*><summary>Full doctor report</summary>"
        r'<pre class="json">(.*?)</pre></details>',
        text,
        re.S,
    )
    assert m and json.loads(html.unescape(m.group(1))) == doc.report
    assert "<script>alert(1)" not in text and "&lt;script&gt;" in text
    assert doc.calls == [False]  # request=False only: no consent prompt, ever


def test_health_outbound_row_is_locked_text_with_the_command(doc):
    text = get("/health").text
    sending = registry.outbound_status()["registered"]
    command = "macos-apps-mcp allow-send " + ("off" if sending else "mail")
    assert f"<code>{command}</code>" in text and f'data-copy="{command}"' in text
    assert sub_of(text, "Outbound").startswith(
        f"Send enabled for: {', '.join(sending)}" if sending else "Send off"
    )
    # no form, no input for the gate: the page has none besides the sidebar's links
    assert "<form" not in text and "<input" not in text


def test_health_adapters_row_counts_pending_changes(doc, monkeypatch):
    names = sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": names, "configured": names[:-2]},
    )
    text = get("/health").text
    sub = sub_of(text, "Adapters")
    assert sub.startswith(f"{len(names)} active: ") and sub.endswith(
        "— 2 pending restart"
    )
    assert re.search(r'<a class="btn" href="/adapters">Show</a>', text)


# --- Health: single flight, off the loop (RESEARCH C7) ----------------------------


def test_health_busy_and_single_flight(doc, monkeypatch):
    monkeypatch.setattr(health, "_WAIT", 0.2)
    doc.gate = threading.Event()
    try:
        first = get("/health")  # the fake blocks; the wait bound ends the request
        assert first.status_code == 200
        busy = "worker busy, a native call is in flight"
        assert busy in first.text and "Deployment" in first.text
        assert value_of(first.text, "Listens on") == "127.0.0.1:47632 (loopback only)"
        assert "Full doctor report" not in first.text
        assert len(doc.calls) == 1

        second = get("/health")  # a call is still in flight: no second call starts
        assert busy in second.text and "Deployment" in second.text
        assert len(doc.calls) == 1
    finally:
        doc.gate.set()
    deadline = time.monotonic() + 5
    while health._lock.locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not health._lock.locked()  # the abandoned thread released the lock
    third = get("/health")
    assert "worker busy" not in third.text and "Full doctor report" in third.text
    assert len(doc.calls) == 2


def test_health_an_exception_in_doctor_never_sticks_the_lock(doc, monkeypatch):
    def boom(request=False):
        raise RuntimeError("EventKit exploded <b>")

    monkeypatch.setattr(doctor, "diagnose", boom)
    r = get("/health")
    assert r.status_code == 200
    assert "doctor could not run" in r.text and "EventKit exploded &lt;b&gt;" in r.text
    assert not health._lock.locked()
    monkeypatch.setattr(doctor, "diagnose", doc.diagnose)
    assert "Full doctor report" in get("/health").text


# --- Health: what cannot work (D-14) ----------------------------------------------

FDA_DENIED = {"full_disk_access": ("fda", False, "denied")}
SETTINGS = "x-apple.systempreferences:com.apple.preference.security?"
EVERYONE = sorted({r.adapter for r in registry.TOOLS.values() if r.adapter})


def banner(text):
    m = re.search(
        r'<div class="banner bad"><span aria-hidden="true">●</span>'
        r"<div><b>(.*?)</b> (.*?)</div></div>",
        text,
        re.S,
    )
    return (html.unescape(m.group(1)), html.unescape(m.group(2))) if m else None


def test_every_banner_glyph_is_hidden_from_screen_readers(doc):
    sources = "".join(
        p.read_text() for p in Path(dashboard.__file__).parent.glob("*.py")
    )
    assert not re.search(r'class="banner[^"]*"><span>', sources)
    assert sources.count('<span aria-hidden="true">') >= 9
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)  # the ● banner
    assert '<span aria-hidden="true">●</span>' in get("/health").text


def row_of(text, title):
    chunks = text.split('<div class="row')
    return next(c for c in chunks if f'<div class="title">{title}</div>' in c)


def only_active(monkeypatch, names):
    monkeypatch.setattr(
        registry, "adapter_status", lambda: {"registered": names, "configured": names}
    )


def needing(service):
    return sorted(
        a
        for a, needs in grants.ADAPTER_GRANTS.items()
        if any(s == service for s, _ in needs)
    )


def test_banner_names_every_active_adapter_macos_refused(doc):
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    names = needing("kTCCServiceSystemPolicyAllFiles")
    assert len(names) == 4  # mail, messages, photos, reminders
    text = get("/health").text
    head, rest = banner(text)
    assert head == "4 active adapters cannot work:"
    # Mail's FDA denial is not an Automation denial: its Automation row stays away
    assert "Automation → Mail" not in text
    listed = ", ".join(f"{n.capitalize()} (denied)" for n in names)
    assert rest == f"{listed}. Grant access, or turn the adapter off."


def test_banner_counts_only_the_active_set(doc, monkeypatch):
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    only_active(monkeypatch, ["photos"])
    head, rest = banner(get("/health").text)
    assert head == "1 active adapter cannot work:"
    assert rest == "Photos (denied). Grant access, or turn the adapter off."


def test_no_banner_when_every_grant_is_granted(doc):
    doc.report = make_report(make_ids(skip=()))
    text = get("/health").text
    assert "banner bad" not in text and "Automation →" not in text


def test_an_automation_denial_is_a_row_and_a_banner_entry(doc):
    doc.report = make_report(make_ids(skip=(), denied=("notes",)))
    text = get("/health").text
    assert banner(text)[0] == "1 active adapter cannot work:"
    assert banner(text)[1].startswith("Notes (denied).")
    row = row_of(text, "Automation → Notes")
    assert "dot bad" in row and ">Denied<" in row
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row


def test_automation_row_not_asked_has_an_accent_dot_and_a_settings_link(doc):
    row = row_of(get("/health").text, "Automation → Music")  # no TCC row for Music
    assert "dot warn" in row and "not asked" in row.lower()
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row


def test_an_off_adapter_raises_no_banner_and_says_it_does_not_matter(doc, monkeypatch):
    only_active(monkeypatch, [a for a in EVERYONE if a != "music"])
    text = get("/health").text
    row = row_of(text, "Automation → Music")
    assert not re.search(r"dot (ok|warn|bad)", row)
    assert "· adapter is off, so this does not matter" in row
    assert "Open Settings" not in row
    assert "banner bad" not in text


def test_an_unreadable_tcc_database_says_so_and_never_claims_not_asked(
    doc, monkeypatch
):
    doc.report = make_report(
        None, calendar=("eventkit", False, "denied")
    )  # TCC unreadable: the EventKit surface is the source
    doc.reasons = {"user": "absent", "system": "absent"}
    text = get("/health").text
    assert banner(text) == (
        "1 active adapter cannot work:",
        "Calendar (denied). Grant access, or turn the adapter off.",
    )
    assert "could not be read" in text and "user db: absent" in text
    assert "not asked" not in text.lower() and "Automation → " not in text
    assert f'href="{SETTINGS}Privacy_Automation">Open Settings</a>' in row_of(
        text, "Automation"
    )


def test_a_partial_tcc_read_never_claims_not_asked(doc):
    # this Mac: the user database is absent, the system one answered with the FDA row
    ids = {"kTCCServiceSystemPolicyAllFiles": [{"client": BUNDLE, "granted": True}]}
    doc.report = make_report(ids)
    doc.reasons = {"user": "absent", "system": None}
    text = get("/health").text
    assert "not asked" not in text.lower() and "banner bad" not in text
    assert "cannot be read here" in text and "Automation → " not in text


def test_a_grant_with_a_status_is_not_a_denial(doc):
    ids = make_ids(skip=())
    ids["kTCCServiceCalendar"][0].update(granted=False, status="limited")
    doc.report = make_report(ids)
    assert "banner bad" not in get("/health").text


def nav_health(text):
    m = re.search(r'<a class="nav-item[^"]*" href="/health"[^>]*>(.*?)</a>', text, re.S)
    return m.group(1)


def test_the_sidebar_dot_follows_the_last_health_report(doc, monkeypatch):
    assert "dot" not in nav_health(get("/usage").text)  # before any report
    doc.report = make_report(make_ids(fda=False), **FDA_DENIED)
    get("/health")
    assert '<span class="dot bad"></span>' in nav_health(get("/usage").text)
    doc.report = make_report(make_ids(skip=()))
    get("/health")
    assert '<span class="dot ok"></span>' in nav_health(get("/usage").text)
    monkeypatch.setattr(
        registry,
        "adapter_status",
        lambda: {"registered": EVERYONE, "configured": EVERYONE[:-1]},
    )
    get("/health")
    assert '<span class="dot warn"></span>' in nav_health(get("/usage").text)


# --- Backups (D-13) ---------------------------------------------------------------

RID1 = "20261020-101500-000001-000-move"
RID2 = "20261021-093100-000002-001-trash"
RID4 = "20261022-120000-000003-1000-move"  # a counter past 999 (#419)
LINK = "20261019-080000-000001-000-move"  # a symlink named like a receipt
KB = 1024


def backup_root():
    return audit.state_dir() / "backup" / "mail"


def eml(folder, name, size):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"x" * size)


def put(*records):
    with (audit.state_dir() / "audit.jsonl").open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def plan_for(rid, ids, *, destination="Archive", op="move"):
    folder = backup_root() / rid
    base = {"tool": "mail_recover", "op": op, "receipt": rid}
    targets = [
        {
            "id": i,
            "folder": "INBOX",
            "fidelity": "full",
            "backup": f"{folder}/{n}.eml",
            "status": "planned",
        }
        for n, i in enumerate(ids, 101)
    ]
    return [
        {
            **base,
            "ts": "2026-10-20T10:15:00",
            "phase": "plan",
            "destination": destination,
            "backup_dir": str(folder),
            "targets": targets,
        },
        {
            **base,
            "ts": "2026-10-20T10:15:02",
            "phase": "done",
            "results": {i: "ok" for i in ids},
        },
    ]


@pytest.fixture
def tree(tmp_path):
    """Two receipts on disk (the first with its plan in the log), a stray folder, and a
    symlink named like a receipt that points outside the backup root."""
    eml(backup_root() / RID1, "101.eml", 1024 * KB)
    eml(backup_root() / RID1, "102.eml", 512 * KB)
    eml(backup_root() / RID2, "201.eml", KB)
    (backup_root() / "notes").mkdir()
    outside = tmp_path / "outside"
    eml(outside, "9.eml", 50 * 1024 * KB)
    (backup_root() / LINK).symlink_to(outside)
    put(*plan_for(RID1, ["a1@x.invalid", "b2@x.invalid"]))
    return tmp_path


def rows_in(text):
    return re.findall(r'<a class="row clickable[^"]*" href="([^"]+)"', text)


def test_backups_page_lists_the_receipts_on_disk_newest_first(tree):
    r = get("/backups")
    assert r.status_code == 200
    text = r.text
    assert "<h1>Backups</h1>" in text
    assert (
        "Every batch Mail write copies its messages to disk first. "
        "Nothing here is ever pruned." in text
    )
    assert "1.5 MB in 2 receipts" in text
    assert "oldest 2026-10-20" in text and "MACOS_APPS_BACKUP_LIMIT" in text
    limit = mail_recover.backup_limit()
    assert re.search(rf'<meter[^>]* max="{limit}"[^>]* value="\d+"', text) or (
        re.search(rf'<meter[^>]* value="\d+"[^>]* max="{limit}"', text)
    )
    assert f'data-copy="{backup_root()}"' in text
    assert rows_in(text) == [f"/backups/{RID2}", f"/backups/{RID1}"]
    assert "move · 2 messages → Archive" in text and "trash · 1 message<" in text
    assert "notes" not in " ".join(rows_in(text)) and LINK not in text
    assert re.search(r'<a class="nav-item active" href="/backups"', text)


def test_backups_row_names_the_destination_account(tree, monkeypatch):
    monkeypatch.setattr(mail_addressing, "_ACCOUNT_MAP_CACHE", {"UUID-1": "Personal"})
    eml(backup_root() / RID4, "301.eml", KB)
    trash = "imap://UUID-1/%5BGmail%5D/Trash"
    put(*plan_for(RID4, ["c3@x.invalid"], destination=trash))
    assert "move · 1 message → Personal › [Gmail]/Trash" in get("/backups").text


def test_backups_page_lists_a_receipt_with_a_four_digit_counter(tree):
    eml(backup_root() / RID4, "301.eml", 2 * KB)
    text = get("/backups").text
    assert rows_in(text)[0] == f"/backups/{RID4}"
    assert "in 3 receipts" in text
    assert get(f"/backups/{RID4}").status_code == 200


def test_backups_escapes_what_the_log_wrote(tree):
    put(*plan_for(RID2, ["c3@x.invalid"], destination="<script>alert(1)</script>"))
    text = get("/backups").text
    assert "<script>alert(1)" not in text and "&lt;script&gt;alert(1)" in text


def test_a_receipt_with_its_plan_opens_the_read_only_batch(tree):
    text = get(f"/backups/{RID1}").text
    assert "<b>2 of 2</b> moved" in text and "101.eml" in text
    assert "To undo, ask Claude" in text and f"Undo mail receipt {RID1}" in text
    assert "<form" not in text and "<input" not in text  # no route writes


def test_a_receipt_whose_plan_rotated_out_lists_its_files(tree):
    eml(backup_root() / RID2, "202.eml", 3 * KB)
    outside = tree / "outside" / "9.eml"
    (backup_root() / RID2 / "999.eml").symlink_to(outside)
    os.mkfifo(backup_root() / RID2 / "fifo.eml")
    text = get(f"/backups/{RID2}").text
    assert "rotated out of the audit log" in text and "files remain" in text
    assert "201.eml" in text and "202.eml" in text
    assert "999.eml" not in text and "fifo.eml" not in text
    assert "To undo, ask Claude" not in text and "Undo mail receipt" not in text
    assert "1 KB" in text


def test_bad_receipts_are_404_and_regex_comes_before_the_disk(tree, monkeypatch):
    def no_disk():
        raise AssertionError("a malformed receipt reached the filesystem")

    monkeypatch.setattr(recovery, "backup_root", no_disk)
    for bad in (
        "..%2f..%2fetc",
        "notes",
        "20261021-093100-000002-001-nope",
        f"{RID1}x",
        "%2e%2e",
    ):
        assert get(f"/backups/{bad}").status_code == 404, bad


def test_a_symlinked_receipt_and_an_unknown_one_are_404(tree):
    assert get(f"/backups/{LINK}").status_code == 404  # real name, symlink folder
    assert get("/backups/20261030-000000-000009-000-move").status_code == 404
    assert "outside" not in get("/backups").text


def test_without_a_backup_root_the_page_is_empty_and_creates_nothing(tree, monkeypatch):
    def never(*a, **kw):
        raise AssertionError("a page must not create, prune or delete a backup")

    for name in ("purge_backup", "_backup_dir"):
        monkeypatch.setattr(mail_recover, name, never)
    import shutil

    shutil.rmtree(backup_root().parent)
    text = get("/backups").text
    assert "0.0 MB in 0 receipts" in text and rows_in(text) == []
    assert get(f"/backups/{RID1}").status_code == 404
    assert not (audit.state_dir() / "backup").exists()


# --- post-merge review of #421 --------------------------------------------------


def test_the_worker_refuses_a_second_doctor_run_while_one_is_in_flight(doc):
    # The page's locked() check is a fast path that two requests can both pass: only
    # the acquire inside the worker thread keeps doctor to one call at a time.
    doc.gate = threading.Event()
    first = threading.Thread(target=health._run)
    first.start()
    try:
        for _ in range(500):
            if doc.calls:
                break
            time.sleep(0.01)
        assert health._run() is None
    finally:
        doc.gate.set()
        first.join(10)
    assert doc.calls == [False]


def test_an_absent_user_grant_db_is_a_note_not_a_warning(doc):
    # #261: macOS 27 keeps no per-user TCC.db, so Automation, Calendar and Reminders
    # grants cannot be read; the rows stay without a chip, never "not asked".
    doc.reasons = {"user": "absent", "system": None}
    text = get("/health").text
    assert "did not answer" not in text and 'class="banner warn"' not in text
    assert "keeps no per-user grant database" in text
    assert "not asked" not in text


def test_receipt_ids_take_ascii_digits_only():
    assert recovery.RECEIPT_RE.fullmatch("20260928-094010-123456-001-move")
    assert not recovery.RECEIPT_RE.fullmatch("٢" * 8 + "-094010-123456-001-move")
    assert not recovery.RECEIPT_RE.fullmatch("20260928-094010-123456-１２３-move")
