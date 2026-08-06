"""0.9.3 — Mail cleanup: trash_mail (#80), the dedupe CLI (#140/#153), mail_duplicates,
and backup storage visibility (#163).

Unit-tested at the module's own seams — sqlite through ``mail_index``, AppleScript
through ``run_osascript`` — so nothing here launches Mail. Per CLAUDE.md a green suite
proves nothing about Mail's real behaviour; the device half is in
``docs/mail-applescript-facts.md`` §5c and the manual verification in the 0.9.3 notes.

The single most important thing these tests pin is that **a delete does not verify the
way a move does**. Mail's `delete` is asynchronous on BOTH sides, so an immediate
one-shot check reports a false failure on a delete that plainly worked — and a false
failure is not cosmetic: it drops the message from the receipt's undo plan, which is
exactly how it was caught (a green suite did not). `_TRASH` therefore waits, bounded,
for the destination to GROW, and `_DEDUPE` verifies in a second pass over the whole
batch that exactly one copy survives.
"""

from __future__ import annotations

import pytest

from macos_apps_mcp import dedupe
from macos_apps_mcp.adapters import mail as mail_mod
from macos_apps_mcp.adapters import mail_index, mail_recover
from macos_apps_mcp.adapters.mail import MailAdapter
from macos_apps_mcp.errors import NativeError
from macos_apps_mcp.text import RS, US

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
BOX = f"imap://{ACCT}/Travel"
TRASH = f"imap://{ACCT}/Trash"


@pytest.fixture
def wired(monkeypatch):
    """Adapter with both boundaries faked: the index answers a Trash url and no
    backups, the AppleScript layer records its calls and replies "ok" per id."""
    calls = []

    def fake_osascript(script, *args, **kwargs):
        calls.append({"script": script, "args": list(args), "kwargs": kwargs})
        ids = args[-1].split(US) if args else []
        return "".join(f"{mid}{US}ok{RS}" for mid in ids if mid)

    monkeypatch.setattr(mail_mod, "run_osascript", fake_osascript)
    monkeypatch.setattr(mail_index, "query_trash_url", lambda acct: TRASH)
    # no store on disk: locate stamps every target `absent`, backups write nothing
    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    monkeypatch.setattr(mail_index, "query_message_locations", lambda ids: [])
    return MailAdapter(), calls


# --- trash_mail (#80) ----------------------------------------------------------------


def test_trash_mail_dry_run_previews_through_the_plane_and_moves_nothing(wired):
    adapter, calls = wired
    out = adapter.trash_mail("<a@x>,<b@x>", BOX, dry_run=True)
    assert mail_recover.is_preview(out)
    assert out["op"] == "trash" and out["count"] == 2
    assert out["destination"] == TRASH
    # exactly one script ran, and it is the PRESENCE probe, never the delete
    assert len(calls) == 1
    assert calls[0]["script"] is mail_mod._PRESENT


def test_delete_verification_waits_because_delete_is_async_on_both_sides():
    # Device-measured 2026-08-05, and it cost a false failure to learn: `delete` is
    # asynchronous on BOTH sides. A one-shot destination count reported "did not appear
    # in Trash" for a message that was demonstrably in Trash, because a back-to-back
    # batch had not settled yet. So the success test is a BOUNDED WAIT on the
    # destination growing — bounded, never `while true` (facts §8).
    for script in (mail_mod._TRASH, mail_mod._DEDUPE):
        assert "repeat 12 times" in script, "the bounded wait was removed"
        assert "delay 0.5" in script
    # _TRASH verifies the destination GREW (a single-copy target may already have had a
    # copy in Trash, so presence alone proves nothing).
    assert "> beforeTrash" in mail_mod._TRASH
    # _DEDUPE verifies in a SECOND pass that exactly ONE copy survives — which also
    # catches over-deletion (0 left), unlike counting how much Trash grew.
    assert "survivors is 1" in mail_mod._DEDUPE
    assert mail_mod._DEDUPE.index(
        "delete (item i of matches)"
    ) < mail_mod._DEDUPE.index("survivors"), (
        "verification must be a second pass, after every delete in the batch"
    )
    # _MOVE's synchronous both-sides assertion must NOT be copied here: source absence
    # may only CONFIRM success (Trash lagging), never declare failure.
    tail = mail_mod._TRASH.split("delete (messages of src")[1]
    fail_branch = tail.split("else")[-1]
    assert "count of (messages of src" not in fail_branch


def test_trash_mail_acts_through_the_plane_and_returns_an_undoable_receipt(wired):
    adapter, calls = wired
    out = adapter.trash_mail("<a@x>,<b@x>", BOX, dry_run=False)
    assert out["op"] == "trash"
    assert out["succeeded"] == 2
    assert out["destination"] == TRASH
    assert out["undo"] == f'mail_undo("{out["receipt"]}")'
    # the delete script ran with source AND trash mailbox args, ids last
    delete_call = [c for c in calls if c["script"] is mail_mod._TRASH][0]
    assert delete_call["args"][:4] == [ACCT, "Travel", ACCT, "Trash"]
    # BARE ids on the wire — the form the scripts echo back, as move_mail sends them
    assert delete_call["args"][4] == f"a@x{US}b@x"


def test_trash_mail_refuses_a_unified_mailbox_name(wired):
    # A canonical name cannot say WHICH account's Trash the message lands in, and Mail
    # will not answer `trash mailbox of <account>` (-1728, §5c). Refuse rather than
    # guess an account.
    adapter, _ = wired
    with pytest.raises(ValueError, match="unified accessor"):
        adapter.trash_mail("<a@x>", "inbox", dry_run=True)


def test_trash_mail_refuses_when_the_source_is_already_trash(wired):
    # `delete` on a message already in Trash is a silent no-op (§5c) — so this would
    # report success having done nothing. Refuse loudly instead.
    adapter, _ = wired
    with pytest.raises(ValueError, match="already in Trash"):
        adapter.trash_mail("<a@x>", TRASH, dry_run=True)


def test_trash_mail_refuses_when_the_account_has_no_trash(wired, monkeypatch):
    adapter, _ = wired
    monkeypatch.setattr(mail_index, "query_trash_url", lambda acct: None)
    with pytest.raises(NativeError, match="no Trash mailbox"):
        adapter.trash_mail("<a@x>", BOX, dry_run=False)


def test_trash_mail_enforces_the_plane_cap(wired):
    adapter, calls = wired
    from macos_apps_mcp.errors import BatchTooLarge

    ids = ",".join(f"<m{i}@x>" for i in range(26))
    with pytest.raises(BatchTooLarge):
        adapter.trash_mail(ids, BOX, dry_run=False)
    assert calls == [], "the cap must be enforced BEFORE any native call"


# --- dedupe (#140) -------------------------------------------------------------------


def test_dedupe_batch_is_log_only_and_skips_the_file_backup(wired):
    adapter, _ = wired
    out = adapter.dedupe_batch("<a@x>", BOX, dry_run=False)
    assert out["op"] == "dedupe"
    # backup=False: the surviving copy IS the backup, so no directory is claimed
    assert "backup_dir" not in out


def test_dedupe_skips_locating_when_it_is_not_backing_up(monkeypatch):
    # locate() rglobs a 36k-file tree; with no backup and no permanent op it serves
    # nobody, and the dedupe CLI drives thousands of messages through here.
    called = []
    monkeypatch.setattr(mail_recover, "locate", lambda t: called.append(1) or list(t))
    mail_recover.recoverable(
        "dedupe",
        [mail_recover.Target(id="<a@x>", folder=BOX)],
        lambda targets: {"<a@x>": "ok"},
        destination=TRASH,
        backup=False,
    )
    assert called == [], "locate ran for a log-only op"


def test_dedupe_keeps_one_copy_by_deleting_in_reverse_index_order():
    # AppleScript cannot address ONE duplicate row (no ROWID in the dictionary), so the
    # survivor is item 1 and items n..2 are deleted in reverse — the §6 rule. A forward
    # loop here would invalidate the reference (-1728) and a `delete (messages ... whose
    # message id is X)` would take the survivor too.
    assert "repeat with i from n to 2 by -1" in mail_mod._DEDUPE
    assert "delete (item i of matches)" in mail_mod._DEDUPE


def test_dedupe_sets_only_collapse_byte_identical_copies():
    rows = [
        {"message_id": "<same@x>", "rowid": 1, "size": 100, "date_sent": 5},
        {"message_id": "<same@x>", "rowid": 2, "size": 100, "date_sent": 5},
        {"message_id": "<differs@x>", "rowid": 3, "size": 100, "date_sent": 5},
        {"message_id": "<differs@x>", "rowid": 4, "size": 999, "date_sent": 5},
        {"message_id": "<lonely@x>", "rowid": 5, "size": 100, "date_sent": 5},
    ]
    safe, skipped = dedupe._sets(rows)
    assert safe == ["<same@x>"]
    assert [s["id"] for s in skipped] == ["<differs@x>"]
    assert skipped[0]["sizes"] == [100, 999]


def test_dedupe_chunks_within_the_plane_cap():
    items = [f"<m{i}@x>" for i in range(25)]
    chunks = list(dedupe._chunks(items))
    assert sum(chunks, []) == items, "chunking must not drop or reorder work"
    assert all(len(c) <= mail_recover.MAX_TARGETS for c in chunks)
    # 56s per set is the DEGRADED-Mail worst case, not the normal one — re-measured
    # 2026-08-06 on a healthy Mail at 0.98 s/set in the same mailbox (#164). Sizing the
    # chunk against the bad number is the point: the run that overruns the timeout is
    # precisely the one on a sick Mail, and dying mid-flight leaves a plan record with
    # no outcome record. Keep ~2x headroom against the worst case.
    assert dedupe._CHUNK * 56 * 2 <= mail_mod._DEDUPE_TIMEOUT


def test_cross_account_requires_an_explicit_keep_account():
    # #153: which account wins is a human decision and no heuristic may make it.
    with pytest.raises(SystemExit) as e:
        dedupe._parse(["--cross-account"])
    assert e.value.code == 2
    opts = dedupe._parse(["--cross-account", "--keep-account=ACCT-1"])
    assert opts["keep_account"] == "ACCT-1"


# --- #153 cross-account plan ---------------------------------------------------------
# Each test below is one of the three refusals. They are the whole safety story: the
# same-mailbox pass can pick an arbitrary survivor because the copies are
# interchangeable, and NONE of that holds across accounts.

KEEP = "ACCT-KEEP"
OTHER = "ACCT-OTHER"


def _copy(mid, account, rowid, mailbox=None):
    return {
        "message_id": mid,
        "rowid": rowid,
        "account": account,
        "mailbox_url": mailbox or f"imap://{account}/Archive",
    }


def test_cross_account_plan_deletes_only_from_non_keeper_mailboxes():
    rows = [_copy("<a@x>", KEEP, 1), _copy("<a@x>", OTHER, 2)]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h", 2: "h"})
    assert plan["keepers"] == {"<a@x>": KEEP}
    # the loser is addressed by ITS OWN mailbox url — the keeper's is never a target
    assert plan["losers"] == {f"imap://{OTHER}/Archive": ["<a@x>"]}
    assert plan["skipped"] == []


def test_cross_account_plan_refuses_a_set_the_keeper_does_not_hold():
    # Without this, `--keep-account=KEEP` would delete BOTH copies of a message KEEP
    # never had — deletion, not deduplication. This is what makes the flag mean
    # something.
    rows = [_copy("<b@x>", OTHER, 1), _copy("<b@x>", "ACCT-THIRD", 2)]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h", 2: "h"})
    assert plan["losers"] == {}
    assert plan["keepers"] == {}
    assert plan["skipped"][0]["why"] == "no copy in the keep-account"


def test_cross_account_plan_refuses_when_a_body_could_not_be_read():
    # A missing fingerprint means "could not compare", never "compared equal". Treating
    # unknown as identical is how a cleanup eats a message that was not a duplicate.
    rows = [_copy("<c@x>", KEEP, 1), _copy("<c@x>", OTHER, 2)]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h"})  # rowid 2 unreadable
    assert plan["losers"] == {}
    assert plan["skipped"][0]["why"] == "a copy has no readable body to compare"


def test_cross_account_plan_refuses_when_the_bodies_differ():
    # Same Message-ID, different body = a forwarded or edited copy. #153 says this must
    # never be collapsed, and it is why Message-ID alone is not the gate.
    rows = [_copy("<d@x>", KEEP, 1), _copy("<d@x>", OTHER, 2)]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h1", 2: "h2"})
    assert plan["losers"] == {}
    assert plan["skipped"][0]["why"] == "bodies differ — not the same message"


def test_cross_account_plan_leaves_same_account_copies_to_140():
    # Two rows in ONE account are #140's job. Collapsing them here would double-delete,
    # and a Gmail label row deleted "twice" takes the message out of every label.
    rows = [_copy("<e@x>", KEEP, 1, "imap://ACCT-KEEP/INBOX"), _copy("<e@x>", KEEP, 2)]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h", 2: "h"})
    assert plan["losers"] == {}
    assert plan["keepers"] == {}
    assert plan["skipped"] == []


def test_cross_account_pass_speaks_mails_id_spelling_not_sqlites(monkeypatch):
    # The index stores `<a@b>`; AppleScript's `message id` reports `a@b`. Feeding the
    # bracketed form downstream does NOT fail loudly — the deletes match nothing and
    # every keeper reads as missing. Caught on device, so it is pinned here.
    rows = [
        {
            "message_id": "<a@x>",
            "rowid": 1,
            "account": KEEP,
            "mailbox_url": f"imap://{KEEP}/Archive",
        },
        {
            "message_id": "<a@x>",
            "rowid": 2,
            "account": OTHER,
            "mailbox_url": f"imap://{OTHER}/Archive",
        },
    ]
    monkeypatch.setattr(mail_index, "query_cross_account_rows", lambda: rows)
    monkeypatch.setattr(mail_index, "query_cross_account_summary", lambda: [])
    monkeypatch.setattr(mail_index, "body_fingerprints", lambda ids: {1: "h", 2: "h"})
    seen = {}

    class _Adapter:
        def presence(self, ids, mailbox):
            return {}

    monkeypatch.setattr(dedupe, "MailAdapter", _Adapter)

    def _spy(r, k, f):
        seen["rows"] = r
        return {"losers": {}, "keepers": {}, "skipped": []}

    monkeypatch.setattr(dedupe, "cross_account_plan", _spy)
    dedupe._run_cross_account(
        {
            "keep_account": KEEP,
            "execute": False,
            "verbose": False,
            "limit": None,
            "mailbox": None,
        }
    )
    assert [r["message_id"] for r in seen["rows"]] == ["a@x", "a@x"], (
        "the plan must be built from Mail's bare id spelling, not sqlite's brackets"
    )


def test_cross_account_plan_never_targets_a_copy_already_in_trash():
    # facts §5c: `delete` on a message already in Trash returns cleanly and removes
    # nothing. Targeting those manufactures guaranteed failures that read exactly like
    # #164's dropped deletes — and the copy is already where a delete would put it.
    rows = [
        _copy("<g@x>", KEEP, 1),
        _copy("<g@x>", OTHER, 2, f"imap://{OTHER}/Trash"),
        _copy("<g@x>", "ACCT-ICLOUD", 3, "imap://ACCT-ICLOUD/Deleted%20Messages"),
        _copy("<g@x>", "ACCT-GMAIL", 4, "imap://ACCT-GMAIL/%5BGmail%5D/Trash"),
    ]
    plan = dedupe.cross_account_plan(rows, KEEP, dict.fromkeys([1, 2, 3, 4], "h"))
    assert plan["losers"] == {}, "all three spellings of Trash must be left alone"
    assert plan["keepers"] == {}, "a set with nothing left to do is not a set to do"


def test_cross_account_plan_keeps_every_keeper_copy_when_several_accounts_lose():
    rows = [
        _copy("<f@x>", KEEP, 1),
        _copy("<f@x>", OTHER, 2),
        _copy("<f@x>", "ACCT-THIRD", 3),
    ]
    plan = dedupe.cross_account_plan(rows, KEEP, {1: "h", 2: "h", 3: "h"})
    assert sorted(plan["losers"]) == [
        f"imap://{OTHER}/Archive",
        "imap://ACCT-THIRD/Archive",
    ]
    assert sum(len(v) for v in plan["losers"].values()) == 2  # never 3


def test_dedupe_previews_by_default():
    assert dedupe._parse([])["execute"] is False
    assert dedupe._parse(["--execute"])["execute"] is True


# --- backup storage visibility (#163) ------------------------------------------------


def test_backup_usage_reports_size_receipts_and_oldest(monkeypatch, tmp_path):
    monkeypatch.setattr(mail_recover, "state_dir", lambda: tmp_path)
    root = tmp_path / "backup" / "mail"
    for name, size in [("20260101-000000-0-move", 10), ("20260805-000000-0-trash", 20)]:
        d = root / name
        d.mkdir(parents=True)
        (d / "1.eml").write_bytes(b"x" * size)
    usage = mail_recover.backup_usage()
    assert usage["bytes"] == 30
    assert usage["receipts"] == 2
    assert usage["oldest"] == "20260101"


def test_backup_usage_never_raises_on_a_missing_tree(monkeypatch, tmp_path):
    # It rides in every doctor() report; a storage read must not fail a diagnostic.
    monkeypatch.setattr(mail_recover, "state_dir", lambda: tmp_path / "nope")
    assert mail_recover.backup_usage()["bytes"] == 0


def test_advisory_is_silent_under_the_threshold_and_names_the_remedy_over_it(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(mail_recover, "state_dir", lambda: tmp_path)
    d = tmp_path / "backup" / "mail" / "20260805-000000-0-trash"
    d.mkdir(parents=True)
    (d / "1.eml").write_bytes(b"x" * 5000)
    monkeypatch.setenv("MACOS_APPS_BACKUP_LIMIT", "10000")
    assert mail_recover.backup_advisory() is None
    monkeypatch.setenv("MACOS_APPS_BACKUP_LIMIT", "1000")
    advisory = mail_recover.backup_advisory()
    assert "rm -r" in advisory
    assert "Do not delete them yourself" in advisory


def test_backup_limit_falls_back_on_a_junk_value(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_BACKUP_LIMIT", "not-a-number")
    assert mail_recover.backup_limit() == mail_recover._DEFAULT_BACKUP_LIMIT
    monkeypatch.setenv("MACOS_APPS_BACKUP_LIMIT", "2048")
    assert mail_recover.backup_limit() == 2048


def test_no_pruning_code_exists_anywhere_in_the_plane():
    # #163's decision is keep-forever. The failure this guards against is a later
    # "helpful" cleanup that silently destroys the undo path the plane exists to
    # provide. purge_backup is the ONE deletion, and it is test-only (no tool calls it).
    import inspect

    src = inspect.getsource(mail_recover)
    callers = [
        line
        for line in src.splitlines()
        if "purge_backup(" in line and "def purge_backup" not in line
    ]
    assert callers == [], f"something calls purge_backup: {callers}"


# --- the report tool (#140) ----------------------------------------------------------


def test_mail_duplicates_reports_and_points_at_the_cli(monkeypatch):
    monkeypatch.setattr(
        mail_index,
        "query_duplicate_summary",
        lambda: [{"mailbox_url": BOX, "total": 10, "distinct_": 4, "redundant": 6}],
    )
    monkeypatch.setattr(
        mail_index,
        "query_duplicate_offenders",
        lambda limit: [
            {"mailbox_url": BOX, "message_id": "<a@x>", "subject": "hi", "copies": 3}
        ],
    )
    monkeypatch.setattr(mail_index, "query_cross_account_summary", lambda: [])
    out = MailAdapter().duplicates()
    assert out["redundant"] == 6
    assert out["worst"][0]["id"] == "a@x"  # bare, citable
    assert "dedupe-mail" in out["note"]


def test_mail_duplicates_is_registered_read_only():
    import macos_apps_mcp.server as srv

    assert "mail_duplicates" not in srv._WRITE_TOOLS
    assert "trash_mail" in srv._WRITE_TOOLS


def test_dedupe_is_cli_only_and_never_an_mcp_tool():
    # #140's seam decision: the model gets the report, the human gets the deletes.
    import asyncio

    import macos_apps_mcp.server as srv

    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert not [n for n in names if "dedupe" in n]
    from macos_apps_mcp import cli

    assert "dedupe-mail" in cli._ROLES


# --- the check a green suite has twice failed to be ----------------------------------


def test_every_applescript_constant_actually_compiles():
    """osacompile every script the mail adapter builds — in EVERY module of it.

    Scans each mail module for uppercase string constants that look like a script, so
    a new script is covered the moment it is named (keep the `on run argv` convention).
    ``mail_outgoing`` joined the list with #160, which moved the four send scripts out
    of ``mail.py``; a derived test that only knew one module would have silently
    stopped compiling them.

    0.9.2 shipped a `move_mail` that could not compile — a scratch variable named `st`,
    which is an AppleScript reserved word (the "1st" ordinal) — past three code reviews
    and a green 1,024-test suite, because nothing here had ever asked a compiler.
    Mocking `run_osascript` proves the Python around a script; it cannot prove the
    script. This costs milliseconds and catches that whole class.

    Compilation only — `osacompile` parses, it does not talk to Mail, so this needs no
    Automation grant and is safe in the normal suite. Skipped where the tool is absent.
    """
    import shutil
    import subprocess

    if not shutil.which("osacompile"):
        pytest.skip("osacompile is macOS-only")
    from macos_apps_mcp.adapters import mail_addressing, mail_outgoing

    modules = (mail_mod, mail_outgoing, mail_addressing)
    scripts = {
        f"{mod.__name__.rsplit('.', 1)[-1]}.{name}": getattr(mod, name)
        for mod in modules
        for name in dir(mod)
        if name.isupper()
        and isinstance(getattr(mod, name), str)
        # every script in these modules opens with a handler or `on run`
        and ("on run argv" in getattr(mod, name))
    }
    assert scripts, "no AppleScript constants found — did the naming change?"
    # the send plane moved to mail_outgoing (#160) — prove the net still reaches it
    assert any(k.startswith("mail_outgoing.") for k in scripts)
    failures = {}
    for name, source in scripts.items():
        proc = subprocess.run(
            ["osacompile", "-o", "/dev/null", "-"],
            input=source,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            failures[name] = proc.stderr.strip()
    assert not failures, "AppleScript that does not compile: " + "; ".join(
        f"{k}: {v}" for k, v in failures.items()
    )
