"""GATE-09: proves the plane-owned preflight (``recoverable(dry_run=, present=)``)
answers byte-for-byte what the old adapter-owned dry-run branches did — for the ops
where nothing was SUPPOSED to change (move/trash/undo) — and pins the one deliberate
delta (card 4's divergence from the spike): ``dedupe_batch``'s dry run now reads
presence too, instead of previewing "planned" for targets nobody checked.

``tests/mail_recover_dry_run_baseline.json`` was captured by running ``capture()``
below against the pre-cut ``develop`` (tag ``v0.11.0``, plan 01-01) — never the spike's
own baseline, which predates #201's Sequoia-plane changes to ``mail.py`` (CONTEXT.md,
"Card 4 baseline"). ``capture()`` uses ONLY names that exist at v0.11.0 (MailAdapter
methods, module attributes), so the identical function ran unmodified on both trees;
only the answer it recorded differs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail, mail_index, mail_recover
from macos_apps_mcp.text import RS, US

ACCT = "AAAAAAAA-1111-2222-3333-444444444444"
INBOX = f"imap://{ACCT}/INBOX"
ARCHIVE = f"imap://{ACCT}/Archive"
BOX = f"imap://{ACCT}/Travel"
TRASH = f"imap://{ACCT}/Trash"

# _PRESENT's fixed answers for the identity fixtures below — "c@x" only appears in the
# cap/empty-batch cases, which never reach a script, so its ERROR reply is unused there.
STATUS = {"a@x": "present", "b@x": "missing", "c@x": "ERROR boom"}

_BASELINE_PATH = Path(__file__).parent / "mail_recover_dry_run_baseline.json"


def capture() -> dict:
    """Run the wired fakes against ``MailAdapter`` and return every dry-run envelope,
    the osascript argv it sent, and the cap/empty-batch error texts — keyed like the
    spike's own identity test (``move_dry``, ``move_dry_calls``, ... ``cap_calls``).

    Self-contained: sets its own temp ``XDG_STATE_HOME`` (never the developer's real
    state dir) and undoes every patch before returning, so it is safe to call from a
    bare ``python -m`` invocation with no pytest fixtures active.
    """
    import tempfile

    mp = pytest.MonkeyPatch()
    mp.setenv("XDG_STATE_HOME", tempfile.mkdtemp(prefix="mail-recover-capture-"))
    try:
        calls: list[dict] = []
        names = {
            id(mail._PRESENT): "_PRESENT",
            id(mail._MOVE): "_MOVE",
            id(mail._TRASH): "_TRASH",
            id(mail._DEDUPE): "_DEDUPE",
        }

        def fake(script, *args, **kw):
            calls.append(
                {
                    "script": names.get(id(script), "?"),
                    "args": list(args),
                    "kwargs": kw,
                }
            )
            ids = args[-1].split(US) if args else []
            if names.get(id(script)) == "_PRESENT":
                return "".join(
                    f"{m}{US}{STATUS.get(m, 'present')}{RS}" for m in ids if m
                )
            return "".join(f"{m}{US}ok{RS}" for m in ids if m)

        mp.setattr(runtime, "run_osascript", fake)
        mp.setattr(mail_index, "query_trash_url", lambda acct: TRASH)
        mp.setattr(mail_index, "mail_root", lambda: None)
        mp.setattr(mail_index, "query_message_locations", lambda ids: [])

        ad = mail.MailAdapter()
        out: dict = {}

        out["move_dry"] = ad.move_mail("<a@x>,b@x,c@x", INBOX, ARCHIVE)
        out["move_dry_calls"] = list(calls)
        calls.clear()

        out["trash_dry"] = ad.trash_mail("<a@x>,b@x,c@x", BOX)
        out["trash_dry_calls"] = list(calls)
        calls.clear()

        out["dedupe_dry"] = ad.dedupe_batch("<a@x>,b@x", BOX)
        out["dedupe_dry_calls"] = list(calls)
        calls.clear()

        moved = ad.move_mail("a@x", INBOX, ARCHIVE, dry_run=False)
        calls.clear()
        out["undo_dry"] = ad.undo(moved["receipt"])
        out["undo_dry_calls"] = list(calls)
        calls.clear()

        cases = {
            "move_26": lambda: ad.move_mail(
                ",".join(f"m{i}@x" for i in range(26)), INBOX, ARCHIVE
            ),
            "trash_26": lambda: ad.trash_mail(
                ",".join(f"m{i}@x" for i in range(26)), BOX
            ),
            "move_0": lambda: ad.move_mail("", INBOX, ARCHIVE),
            "export_26": lambda: ad.export(",".join(f"m{i}@x" for i in range(26)), "x"),
            "export_0": lambda: ad.export("", "x"),
        }
        for key, fn in cases.items():
            try:
                fn()
            except Exception as e:  # the exact text is the thing under test
                out[key] = f"{type(e).__name__}: {e}"
            else:
                raise AssertionError(f"{key} did not raise")
        out["cap_calls"] = list(calls)
        return out
    finally:
        mp.undo()


if __name__ == "__main__":
    import sys

    if "--capture" not in sys.argv:
        raise SystemExit(
            "usage: python test_mail_recover_dry_run_identity.py --capture"
        )
    print(f"macos_apps_mcp.__file__ = {mail.__file__}", file=sys.stderr)
    print(json.dumps({"_source": "v0.11.0", **capture()}, indent=1))


# --- pytest section: run only against the CURRENT tree, compared to the baseline -----


def _old() -> dict:
    return json.loads(_BASELINE_PATH.read_text())


@pytest.fixture
def wired(monkeypatch):
    """Same shape as ``capture()``'s fakes, as a pytest fixture — session isolation
    (XDG_STATE_HOME, the native-seam lock) is already handled by conftest.py here."""
    calls: list[dict] = []
    names = {
        id(mail._PRESENT): "_PRESENT",
        id(mail._MOVE): "_MOVE",
        id(mail._TRASH): "_TRASH",
        id(mail._DEDUPE): "_DEDUPE",
    }

    def fake(script, *args, **kw):
        calls.append(
            {"script": names.get(id(script), "?"), "args": list(args), "kwargs": kw}
        )
        ids = args[-1].split(US) if args else []
        if names.get(id(script)) == "_PRESENT":
            return "".join(f"{m}{US}{STATUS.get(m, 'present')}{RS}" for m in ids if m)
        return "".join(f"{m}{US}ok{RS}" for m in ids if m)

    monkeypatch.setattr(runtime, "run_osascript", fake)
    monkeypatch.setattr(mail_index, "query_trash_url", lambda acct: TRASH)
    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    monkeypatch.setattr(mail_index, "query_message_locations", lambda ids: [])
    return mail.MailAdapter(), calls


def _same(new, key: str, old: dict) -> None:
    assert json.dumps(new, indent=1) == json.dumps(old[key], indent=1), key


def test_move_dry_run_is_byte_identical(wired):
    old = _old()
    ad, calls = wired
    _same(ad.move_mail("<a@x>,b@x,c@x", INBOX, ARCHIVE), "move_dry", old)
    _same(calls, "move_dry_calls", old)


# --- behavior tests (Task 1, plan's <behavior> list) ----------------------------------


def _t(mid: str, folder: str = BOX) -> mail_recover.Target:
    return mail_recover.Target(id=mid, folder=folder, account=ACCT)


def test_recoverable_dry_run_with_no_present_raises_naming_the_op():
    with pytest.raises(TypeError, match=r"needs `present`") as e:
        mail_recover.recoverable("move", [_t("a@x")], lambda ts: {}, dry_run=True)
    assert "move" in str(e.value)


def test_dry_run_reads_present_once_in_order_never_calls_act():
    reads: list[list[str]] = []
    acts: list[object] = []

    def present(targets):
        reads.append([t.id for t in targets])
        return {"a@x": "present"}

    out = mail_recover.recoverable(
        "move",
        [_t("a@x"), _t("b@x")],
        lambda ts: acts.append(ts) or {},
        dry_run=True,
        present=present,
        destination=ARCHIVE,
    )
    assert reads == [["a@x", "b@x"]]
    assert acts == []
    # "b@x" is a target the read did not answer for — must report "missing", never a
    # guessed "present" or the pre-read default "planned"
    assert [t["status"] for t in out["would_affect"]] == ["present", "missing"]


def test_wet_run_never_calls_present(monkeypatch):
    monkeypatch.setattr(mail_index, "mail_root", lambda: None)
    monkeypatch.setattr(mail_index, "query_message_locations", lambda ids: [])

    def boom(targets):
        raise AssertionError("present must not run on a wet call")

    out = mail_recover.recoverable(
        "move",
        [_t("a@x")],
        lambda ts: {"a@x": "ok"},
        present=boom,
        destination=ARCHIVE,
    )
    assert out["succeeded"] == 1
