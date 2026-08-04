"""``macos-apps-mcp dedupe-mail`` — the duplicate cleanup (#140, #153).

**A CLI command and never an MCP tool.** The scale is the whole argument: ~9.9k
redundant same-mailbox rows, an AppleScript delete costs roughly a tenth of a second,
and ``run_osascript`` caps a script at 30 seconds on a single serialized worker. As an
MCP tool that is either hundreds of model-mediated round trips or a starved daemon. The
repo already has the rule for this shape — ``allow-send`` is a CLI command so the model
cannot grant itself sending, and #119 is a CLI command because it is hours of work a
human should start. This is both.

**Preview is the default.** A bare ``dedupe-mail`` prints the per-mailbox table and
touches nothing; ``--execute`` acts. Resumable by construction: the plan is recomputed
from the index each run, so an interrupted pass simply finds less to do next time.

**How it decides what to delete.** sqlite locates, AppleScript acts — never the reverse,
and nothing here ever writes to Mail's Envelope Index. Within one mailbox, a duplicate
set is the rows sharing an RFC822 Message-ID; a set is only touched when every copy is
byte-identical on ``size`` AND ``date_sent``. That check is not a formality: AppleScript
cannot address one specific copy (there is no ROWID in Mail's dictionary, only "messages
whose message id is X", which matches them all), so the survivor is whichever copy Mail
leaves — see ``mail._DEDUPE``. Identical bytes are what make an unaddressable winner
safe, which is why a mismatched set is skipped and reported instead.

Losers are moved to Trash, not erased — there is no erase (facts doc §5c) — and the pass
is recorded through the recoverable plane's action log in LOG-ONLY mode: the surviving
copy is the backup, so per-loser file copies would be pure cost at this scale.
"""

from __future__ import annotations

import sys

from .adapters import mail_index
from .adapters.mail import MailAdapter
from .adapters.mail_recover import MAX_TARGETS

_USAGE = """usage: macos-apps-mcp dedupe-mail [options]

  (no options)          preview every mailbox — prints the table, changes nothing
  --execute             actually move the redundant copies to Trash
  --verbose             list every set skipped for not being byte-identical
  --mailbox=<url>       restrict to one mailbox (its `folder` url from mail_overview)
  --cross-account       operate on copies of one message held by SEVERAL accounts
  --keep-account=<id>   required with --cross-account: the account whose copy survives

Losers go to Trash — nothing is erased, and Mail cannot erase from a script. Empty the
Trash yourself in Mail.app when you are satisfied.
"""


def _parse(argv: list[str]) -> dict:
    opts = {
        "execute": False,
        "mailbox": None,
        "cross_account": False,
        "keep_account": None,
        "verbose": False,
    }
    for arg in argv:
        if arg == "--execute":
            opts["execute"] = True
        elif arg == "--verbose":
            opts["verbose"] = True
        elif arg == "--cross-account":
            opts["cross_account"] = True
        elif arg.startswith("--mailbox="):
            opts["mailbox"] = arg.split("=", 1)[1]
        elif arg.startswith("--keep-account="):
            opts["keep_account"] = arg.split("=", 1)[1]
        elif arg in ("-h", "--help"):
            print(_USAGE)
            raise SystemExit(0)
        else:
            print(f"unknown option {arg!r}\n\n{_USAGE}", file=sys.stderr)
            raise SystemExit(2)
    # #153's whole point: which account's copy survives is a HUMAN decision, and no
    # heuristic is ever allowed to make it. Refusing here — before a single row is read
    # — is what keeps that promise at the only place a human is present to answer.
    if opts["cross_account"] and not opts["keep_account"]:
        print(
            "--cross-account requires --keep-account=<account-uuid>: which account's "
            "copy survives is your decision, and this command will not guess it.\n"
            "Run `mail_duplicates()` or mail_overview() to see the account ids.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return opts


def _sets(rows: list[dict]) -> tuple[list[str], list[dict]]:
    """Split one mailbox's duplicate rows into (ids safe to collapse, skipped sets).

    Safe means: more than one copy, and every copy byte-identical to the first on size
    and date_sent. A set that fails that test is NOT deleted — it is returned so the
    caller can print it, because two rows sharing a Message-ID while differing in size
    are not the same message whatever the header claims, and this command's licence to
    pick an arbitrary survivor depends entirely on them being interchangeable.
    """
    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(str(row["message_id"]), []).append(row)
    safe, skipped = [], []
    for mid, copies in by_id.items():
        if len(copies) < 2:
            continue
        first = copies[0]
        if all(
            c["size"] == first["size"] and c["date_sent"] == first["date_sent"]
            for c in copies
        ):
            safe.append(mid)
        else:
            skipped.append(
                {
                    "id": mid,
                    "copies": len(copies),
                    "sizes": sorted({c["size"] for c in copies}),
                }
            )
    return safe, skipped


# Sets per receipt. UNDER the plane's cap of 25 (which is a maximum, not a target) for a
# measured reason: on a real IMAP account a set costs **~56 seconds** (timed 2026-08-05:
# a 10-set chunk took 558s), because `messages of mb whose message id is X` is an
# O(mailbox) scan and a 3,454-message mailbox pays it two or three times per set. A
# 25-set batch ran past the 300s host timeout mid-flight — the worst outcome available,
# since the plan record is already written, the deletes are half-applied, and the
# receipt never gets its outcome record.
#
# Eight sets is ~7.5 minutes against the 900s ceiling — roughly 2x margin, which matters
# because the per-set cost is server-bound and varies. Smaller chunks also mean more
# frequent receipts and finer resume granularity, and cost only an extra osascript
# launch (~1s) each.
#
# Consequence worth stating plainly: a big mailbox takes HOURS (Travel's 1,087 sets is
# most of a day). That is the whole reason this is a human-started CLI, and why it is
# resumable rather than transactional.
#
# ponytail: a constant, not a flag. Make it one if a fast local store makes the
# conservatism cost real time — the ceiling is _DEDUPE_TIMEOUT, not this number.
_CHUNK = 8


def _chunks(items: list[str]):
    """Split into receipts. Each chunk is its own backup-free plan/outcome pair in the
    action log, so an interrupted run resumes simply by being re-run (the plan is
    recomputed from the index) and any single receipt can be undone on its own."""
    size = min(_CHUNK, MAX_TARGETS)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _run_mailbox(
    adapter, url: str, execute: bool, verbose: bool
) -> tuple[int, int, int]:
    """Preview or collapse one mailbox. Returns (safe sets, sets collapsed, skipped)."""
    rows = mail_index.query_duplicate_rows(url)
    safe, skipped = _sets(rows)
    redundant = len(rows) - len({str(r["message_id"]) for r in rows})
    name = url.rsplit("/", 1)[-1]
    print(
        f"  {name:<28} {len(safe):>5} sets, {redundant:>5} redundant copies"
        + (f", {len(skipped)} sets skipped (not byte-identical)" if skipped else "")
    )
    # Per-set skip lines are the long tail — hundreds of them on a real store, which
    # buries the table they are meant to annotate. The COUNT is always shown (a silent
    # truncation reads as "covered everything"); --verbose prints which.
    if verbose:
        for s in skipped:
            print(
                f"      SKIPPED {s['id']} — {s['copies']} copies differ in size "
                f"{s['sizes']}; not byte-identical, left alone"
            )
    if not execute or not safe:
        return len(safe), 0, len(skipped)
    removed = 0
    for batch in _chunks(safe):
        result = adapter.dedupe_batch(batch, url, dry_run=False)
        ok = result.get("succeeded", 0)
        removed += ok
        print(
            f"      receipt {result['receipt']}: {ok}/{len(batch)} sets collapsed"
            + ("" if ok == len(batch) else "  ← see the receipt, some did not")
        )
        for t in result.get("targets", []):
            if t.get("status") != "ok":
                print(f"        {t['id']}: {t['status']}")
    return len(safe), removed, len(skipped)


def dedupe_mail(argv: list[str]) -> None:
    """Entry point for the ``dedupe-mail`` role."""
    opts = _parse(argv)
    if opts["cross_account"]:
        # Honest partial: the cross-account half (#153) needs its own winner rule and
        # its own script (the copies live in DIFFERENT mailboxes, so the "keep item 1 of
        # this mailbox's matches" mechanic the same-mailbox pass uses does not apply).
        # Reporting is live; the destructive half is not built yet.
        print("cross-account duplicate copies by account (#153):\n")
        for row in mail_index.query_cross_account_summary():
            print(f"  {row['account']}  {row['copies']:>6} copies")
        print(
            "\nThe cross-account CLEANUP is not implemented yet (#153 stays open). The "
            "same-mailbox pass below is; run `dedupe-mail` with no --cross-account."
        )
        return

    adapter = MailAdapter()
    summary = mail_index.query_duplicate_summary()
    if opts["mailbox"]:
        summary = [r for r in summary if r["mailbox_url"] == opts["mailbox"]]
        if not summary:
            print(
                f"no same-mailbox duplicates in {opts['mailbox']!r} (or the url does "
                "not match one Mail knows — pass the `folder` value verbatim)."
            )
            return

    total_redundant = sum(r["redundant"] for r in summary)
    mode = "EXECUTING" if opts["execute"] else "PREVIEW (nothing will change)"
    print(
        f"{mode} — {total_redundant} redundant rows across {len(summary)} mailboxes\n"
    )
    sets = removed = skipped = 0
    for row in summary:
        s, r, k = _run_mailbox(
            adapter, row["mailbox_url"], opts["execute"], opts["verbose"]
        )
        sets += s
        removed += r
        skipped += k
    print()
    # Never let the skipped tail go unmentioned: a run that quietly leaves duplicates
    # behind reads as "the mailbox is clean now" when it is not.
    residue = (
        f" {skipped} sets were LEFT ALONE because their copies are not"
        " byte-identical"
        " (re-run with --verbose to see which); those need a human eye."
        if skipped
        else ""
    )
    if opts["execute"]:
        print(
            f"done — {removed} of {sets} duplicate sets collapsed.{residue} The "
            "removed copies are in each account's Trash, undoable with "
            "mail_undo(<receipt>) "
            "until you empty it. Emptying Trash is a Mail.app action; nothing here can "
            "do it."
        )
    else:
        print(
            f"{sets} duplicate sets are safe to collapse.{residue} Re-run with "
            "--execute to move the redundant copies to Trash. Start with one mailbox "
            "(--mailbox=<url>) before running the lot."
        )
