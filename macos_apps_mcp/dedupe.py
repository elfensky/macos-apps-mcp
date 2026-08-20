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

**Cross-account (#153) uses a DIFFERENT identity rule, because the same one does not
work.** Measured over all 3,948 cross-account sets on the dev Mac (2026-08-06):
``size + date_sent`` agrees on **1.2%** of them — 1.1% of the 3,926 Google+Personal
sets — because copies that arrived by different paths have different bytes. Gmail
rewrites headers in transit (``X-GM-*``, extra ``Received:``) without touching a word of
the content, so ``date_sent`` always matches and ``size`` almost never does. Gating
cross-account on size would decline 99% of the work it exists to do. The gate there is
the **body**, which #119 made local: 397/397 on a 400-set sample. Message-ID stays the
key and the body hash is only ever the confirmation — a negative control found 6 real
hash collisions in 792 distinct messages (bulk-sender templates), so the hash is not an
identity on its own.

The two passes also differ in who survives. Same-mailbox: the winner is the LEFTOVER
(items n..2 are deleted, item 1 remains) and byte-identity is what makes an
unaddressable survivor safe. Cross-account: the winner is an account a HUMAN NAMED, so
every delete is aimed at a specific non-keeper mailbox and the keeper is PROVEN still
present in a mandatory post-pass.

Losers are moved to Trash, not erased — there is no erase (facts doc §5c). The
same-mailbox pass rides the recoverable plane in LOG-ONLY mode (the byte-identical
survivor IS the backup). The cross-account pass goes through ``trash_mail``, which DOES
write per-message backups — deliberately, and it is the one place these two diverge:
cross-account copies are NOT byte-identical, so the keeper preserves the message's
content but not the loser's exact bytes, and the cheap belt is worth having.
"""

from __future__ import annotations

import sys

from .adapters import mail_addressing, mail_index, mailbox_url
from .adapters.mail import MailAdapter
from .adapters.mail_recover import MAX_TARGETS

_USAGE = """usage: macos-apps-mcp dedupe-mail [options]

  (no options)          preview every mailbox — prints the table, changes nothing
  --execute             actually move the redundant copies to Trash
  --verbose             list every set that was skipped, and why
  --mailbox=<url>       restrict to one mailbox (its `folder` url from mail_overview);
                        with --cross-account this restricts the LOSER mailbox
  --cross-account       operate on copies of one message held by SEVERAL accounts
  --keep-account=<id>[,<id>...]
                        required with --cross-account: whose copy survives. Several ids
                        are an ORDERED PRECEDENCE — the first one holding a copy wins
                        that set, and every other copy loses (including a lower-ranked
                        keeper's). e.g. --keep-account=<business>,<personal>
  --limit=<n>           act on at most n sets — start small, verify, then widen

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
        "limit": None,
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
        elif arg.startswith("--limit="):
            # A destructive pass over 3.9k sets should not be anyone's FIRST run of a
            # new command. This is what makes "start small, inspect both accounts, then
            # widen" an option the CLI offers rather than advice in a docstring.
            try:
                opts["limit"] = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"--limit needs a whole number, got {arg!r}", file=sys.stderr)
                raise SystemExit(2) from None
            if opts["limit"] < 1:
                print("--limit must be at least 1", file=sys.stderr)
                raise SystemExit(2)
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


# "Is this a Trash?" — the shared vocabulary in mailbox_url (#175), the same table
# behind mail_index's _TRASH_SUFFIXES and _MAILBOX_RANK, so the three can't drift
# again (they had: this list knew `Bin`, the rank didn't).
_is_trash = mailbox_url.is_trash


def cross_account_plan(rows: list[dict], keep_account, fingerprints: dict) -> dict:
    """Turn every cross-account copy into {losers-by-mailbox, keepers, skipped}.

    ``keep_account`` is an ORDERED PRECEDENCE — one account id, or several. The first
    one holding a copy of a given set wins that set; every other copy loses, including
    a copy in a lower-ranked keeper. So ``business,personal`` means "if it is in
    Business, that is the copy to keep and Personal's goes too" (operator, 2026-08-08).

    An order is still a HUMAN typing the answer, which is what #153 required — not a
    heuristic the tool invented. What stays forbidden is the tool ranking accounts on
    its own (by size, recency, or anything else); it only ever reads the order given.

    The three refusals here are the whole safety story of #153, and each one exists
    because the alternative silently does the wrong thing:

    1. **No copy in ANY keeper account → SKIP the set.** Otherwise "keep Personal" would
       delete both copies of a message Personal never held, which is not deduplication,
       it is deletion. This is the one that makes ``--keep-account`` mean something.
    2. **Any copy without a body fingerprint → SKIP.** A missing fingerprint means the
       bytes could not be read, not that they matched; treating unknown as identical is
       how a "cleanup" eats a message that was never a duplicate.
    3. **Fingerprints disagree → SKIP.** Same Message-ID with a different body is a
       forwarded or edited copy, exactly the case #153 said must not be collapsed.

    Note what is NOT a rule: same-mailbox copies. Two rows in ONE mailbox are #140's
    job, and collapsing them here would double-delete. Losers are grouped BY MAILBOX
    because that is the only unit Mail's delete can address (facts §5b/§5c).

    A loser already sitting in its account's **Trash is dropped, not targeted**: facts
    §5c, `delete` on a message already in Trash returns cleanly and removes nothing —
    Trash is terminal for AppleScript. Targeting those would manufacture guaranteed
    failures that look exactly like #164's dropped deletes, and the copy is already
    where a delete would have put it. The first dry run found 6 of these.
    """
    # One id or several — a single keeper is just an order of length 1, which is why
    # this stayed one flag instead of growing a second one.
    order = [keep_account] if isinstance(keep_account, str) else list(keep_account)

    by_id: dict[str, list[dict]] = {}
    for row in rows:
        by_id.setdefault(str(row["message_id"]), []).append(row)

    losers: dict[str, list[str]] = {}
    keepers: dict[str, str] = {}
    skipped: list[dict] = []
    for mid, copies in by_id.items():
        accounts = {c["account"] for c in copies}
        if len(accounts) < 2:
            continue  # not cross-account; #140 owns it
        winner = next((a for a in order if a in accounts), None)
        if winner is None:
            skipped.append(
                {
                    "id": mid,
                    "why": "no copy in the keep-account",
                    "accounts": sorted(accounts),
                }
            )
            continue
        prints = [fingerprints.get(int(c["rowid"])) for c in copies]
        if any(p is None for p in prints):
            skipped.append(
                {
                    "id": mid,
                    "why": "a copy has no readable body to compare",
                    "accounts": sorted(accounts),
                }
            )
            continue
        if len(set(prints)) != 1:
            skipped.append(
                {
                    "id": mid,
                    "why": "bodies differ — not the same message",
                    "accounts": sorted(accounts),
                }
            )
            continue
        targets = [
            c
            for c in copies
            if c["account"] != winner and not _is_trash(c["mailbox_url"])
        ]
        if not targets:
            continue  # every loser is already in Trash — nothing left to do
        keepers[mid] = winner  # the account that actually won, not the whole order
        for c in targets:
            losers.setdefault(c["mailbox_url"], []).append(mid)
    return {"losers": losers, "keepers": keepers, "skipped": skipped}


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
    name = mailbox_url.leaf(url)
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


def _run_cross_account(opts: dict) -> None:
    """The #153 pass: collapse copies of one message held by SEVERAL accounts.

    Structurally different from the same-mailbox pass above, and the difference is the
    point. #140 deletes items n..2 of one mailbox's matches and lets item 1 survive —
    the winner is not addressed, it is the LEFTOVER, which is only safe because the
    copies are interchangeable. Here the winner is an account a human NAMED, so every
    delete is aimed at a specific non-keeper mailbox and the keeper is PROVEN present
    afterwards rather than assumed.

    That last pass is what #164 bought. A dropped delete is a no-op and is always
    reported (232 observations, zero silent), so the residual risk is "a loser stayed",
    which a re-run fixes — not "the keeper went", which the post-pass would catch.
    """
    # An ORDER, not one account (operator, 2026-08-08): first listed account holding a
    # copy wins that set. `--keep-account=A` is just an order of length 1.
    order = [a.strip() for a in str(opts["keep_account"]).split(",") if a.strip()]
    adapter = MailAdapter()
    rows = mail_index.query_cross_account_rows()
    if not rows:
        print("no cross-account duplicate copies found.")
        return
    # THE TWO PLANES DISAGREE BY CONSTRUCTION: sqlite stores `<a@b>`, AppleScript's
    # `message id` reports `a@b`. Everything downstream of here — trash_mail's locate,
    # the delete script, the keeper post-pass — speaks Mail's spelling, so normalise
    # once at the boundary. Skipping this does not fail loudly: the deletes match
    # nothing and the post-pass reports every keeper missing.
    rows = [
        {**r, "message_id": mail_addressing.bare_id(str(r["message_id"]))} for r in rows
    ]

    accounts = sorted({r["account"] for r in rows})
    unknown = [a for a in order if a not in accounts]
    if len(unknown) == len(order):
        print(
            "no account in --keep-account holds cross-account copies. Accounts "
            "that do:\n" + "\n".join(f"  {a}" for a in accounts),
            file=sys.stderr,
        )
        raise SystemExit(2)
    for a in unknown:
        # Not fatal while another rank still matches — but never silent, because a
        # typo'd id in an order reads exactly like "that account had no duplicates".
        print(f"note: {a} holds no cross-account copies; it can never win a set.")

    print("cross-account duplicate copies by account (#153):\n")
    for row in mail_index.query_cross_account_summary():
        rank = order.index(row["account"]) + 1 if row["account"] in order else None
        mark = f"  <- KEEPER (rank {rank})" if rank else ""
        print(f"  {row['account']}  {row['copies']:>6} copies{mark}")

    # Body identity, not size+date_sent. Measured across every cross-account set on this
    # Mac: size+date_sent agrees on 1.2% of them, the body on ~100%. Gating on size
    # would decline 99% of the work. See mail_index.body_fingerprints.
    print("\nreading bodies to prove identity (this walks the mail store once)...")
    prints = mail_index.body_fingerprints([r["rowid"] for r in rows])
    plan = cross_account_plan(rows, order, prints)
    losers, keepers, skipped = plan["losers"], plan["keepers"], plan["skipped"]

    # --mailbox restricts the LOSER side here, the same "do one mailbox first" the
    # same-mailbox pass uses it for. Without it there is no way to reach the small
    # accounts at all: one Gmail mailbox holds 3,874 of the 3,890 copies, so every
    # bounded run would be a Gmail run.
    if opts["mailbox"]:
        losers = {u: m for u, m in losers.items() if u == opts["mailbox"]}
        if not losers:
            print(
                f"\nno cross-account losers in {opts['mailbox']!r} — pass a mailbox "
                "url from the table above, verbatim."
            )
            return
        still = {m for mids in losers.values() for m in mids}
        keepers = {k: v for k, v in keepers.items() if k in still}

    limited = 0
    if opts["limit"] is not None and len(keepers) > opts["limit"]:
        # Sorted, so --limit=3 twice in a row means the same three sets — a first run
        # you can inspect and then repeat is worth more than a random sample.
        chosen = set(sorted(keepers)[: opts["limit"]])
        limited = len(keepers) - len(chosen)
        keepers = {k: v for k, v in keepers.items() if k in chosen}
        losers = {
            url: [m for m in mids if m in chosen]
            for url, mids in losers.items()
            if any(m in chosen for m in mids)
        }

    total_losers = sum(len(v) for v in losers.values())

    mode = "EXECUTING" if opts["execute"] else "PREVIEW (nothing will change)"
    print(
        f"\n{mode} — keeping {' > '.join(order)}\n"
        f"  {len(keepers)} sets are safe to collapse, {total_losers} copies would "
        f"go to Trash in {len(losers)} non-keeper mailboxes\n"
        f"  {len(skipped)} sets LEFT ALONE\n"
        # Never let a cap read as "that was everything" — the silent-truncation rule.
        + (
            f"  {limited} further eligible sets held back by --limit\n"
            if limited
            else ""
        )
    )
    for url, mids in sorted(losers.items()):
        print(f"  {url}   {len(mids):>5} copies")
    if skipped:
        why: dict[str, int] = {}
        for s in skipped:
            why[s["why"]] = why.get(s["why"], 0) + 1
        print("\n  left alone, by reason:")
        for reason, n in sorted(why.items(), key=lambda kv: -kv[1]):
            print(f"    {n:>5}  {reason}")
        if opts["verbose"]:
            for s in skipped:
                print(
                    f"      SKIPPED {s['id']} — {s['why']} ({'+'.join(s['accounts'])})"
                )

    if not opts["execute"]:
        print(
            "\nRe-run with --execute to move the non-keeper copies to Trash. Losers go "
            "to each non-keeper account's OWN Trash and are undoable by receipt until "
            "you empty it."
        )
        return

    removed = failed = 0
    for url, mids in sorted(losers.items()):
        print(f"\n  {url}")
        for batch in _chunks(mids):
            result = adapter.trash_mail(batch, url, dry_run=False)
            ok = result.get("succeeded", 0)
            removed += ok
            failed += len(batch) - ok
            print(
                f"      receipt {result['receipt']}: {ok}/{len(batch)} copies trashed"
            )
            for t in result.get("targets", []):
                if t.get("status") != "ok":
                    print(f"        {t['id']}: {t['status']}")

    # THE MANDATORY POST-PASS. Everything above deleted from non-keeper mailboxes; this
    # proves the keeper's copy is still there. It is the one check that distinguishes
    # "honoured --keep-account" from "moved the right number of messages", and #153 does
    # not ship without it.
    print("\nverifying every keeper copy survived...")
    by_mailbox: dict[str, list[str]] = {}
    # Per-set winner, NOT one fixed account: with an order, different sets keep
    # different accounts, and checking a single one would verify the wrong copy — or
    # skip the check entirely for every set the other rank won.
    keeper_rows = [r for r in rows if keepers.get(r["message_id"]) == r["account"]]
    for r in keeper_rows:
        by_mailbox.setdefault(r["mailbox_url"], []).append(r["message_id"])
    lost: list[str] = []
    for url, mids in sorted(by_mailbox.items()):
        for batch in _chunks(mids):
            statuses = adapter.presence(batch, url)
            for mid in batch:
                if statuses.get(mid) != "present":
                    lost.append(f"{mid} ({statuses.get(mid, 'unknown')}) in {url}")
    if lost:
        print(
            f"\n*** {len(lost)} KEEPER COPIES ARE NOT WHERE THEY SHOULD BE ***\n"
            + "\n".join(f"    {x}" for x in lost[:20])
            + "\nUndo the receipts above (mail_undo) and do NOT re-run until this is "
            "understood.",
            file=sys.stderr,
        )
    else:
        print(f"  all {len(keeper_rows)} keeper copies still present.")

    print(
        f"\ndone — {removed} non-keeper copies trashed"
        + (
            f", {failed} NOT affected (see statuses above; re-run is the retry)"
            if failed
            else ""
        )
        + f". {len(skipped)} sets were left alone. The removed copies are in each "
        "account's Trash, undoable with mail_undo(<receipt>) until you empty it."
    )


def dedupe_mail(argv: list[str]) -> None:
    """Entry point for the ``dedupe-mail`` role."""
    opts = _parse(argv)
    if opts["cross_account"]:
        _run_cross_account(opts)
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
