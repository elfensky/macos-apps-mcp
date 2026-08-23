"""mailbox_url (#175) — the one home of the url grammar and the special-mailbox table.

Pure string tests, no fixture: the module is stdlib-only by design. The rank/dedup
BEHAVIOR (which copy wins a citation) is pinned in test_mail_search.py against the
_fake_envelope fixture; here we pin the grammar and the table's consistency.
"""

from __future__ import annotations

from macos_apps_mcp.adapters import mailbox_url

GMAIL_TRASH = "imap://UUID-A/%5BGmail%5D/Trash"


def test_parse_splits_scheme_account_and_decodes_path():
    assert mailbox_url.parse(GMAIL_TRASH) == ("imap", "UUID-A", "[Gmail]/Trash")
    assert mailbox_url.parse("local://UUID-L/Some%20Folder") == (
        "local",
        "UUID-L",
        "Some Folder",
    )


def test_parse_non_url_is_none():
    # A typed name is not a url — the caller's name/url split (#156) turns on this.
    assert mailbox_url.parse("inbox") is None
    assert mailbox_url.parse("") is None


def test_parse_empty_segments_come_back_empty_not_raised():
    # Callers refuse with their own wording; the grammar just reports what's there.
    assert mailbox_url.parse("imap:///INBOX") == ("imap", "", "INBOX")
    assert mailbox_url.parse("imap://UUID-A/") == ("imap", "UUID-A", "")


def test_account_path_leaf():
    assert mailbox_url.account(GMAIL_TRASH) == "UUID-A"
    assert mailbox_url.account("not a url") is None
    assert mailbox_url.path(GMAIL_TRASH) == "[Gmail]/Trash"
    assert mailbox_url.leaf(GMAIL_TRASH) == "Trash"
    assert mailbox_url.leaf("imap://U/Deleted%20Messages") == "Deleted Messages"


def test_make_round_trips_through_parse():
    url = mailbox_url.make("imap", "UUID-A", "Projects/2026")
    assert mailbox_url.parse(url) == ("imap", "UUID-A", "Projects/2026")


def test_is_trash_matches_decoded_leaves():
    assert mailbox_url.is_trash(GMAIL_TRASH)
    assert mailbox_url.is_trash("imap://U/Deleted%20Messages")
    assert mailbox_url.is_trash("imap://U/Bin")
    assert not mailbox_url.is_trash("imap://U/INBOX")
    # leaf-anchored: a user folder that merely CONTAINS a trash word is not a trash
    assert not mailbox_url.is_trash("imap://U/Bin/Keep")  # leaf is Keep
    assert not mailbox_url.is_trash("imap://U/Binder")


def test_trash_suffixes_cover_every_trash_spelling_and_only_those():
    # The two SQL-side questions must agree with the membership test — the drift this
    # module ends (#175: dedupe knew Bin, the rank didn't).
    assert set(mailbox_url.TRASH_SUFFIXES) == {
        r"%/Trash",
        r"%/Deleted\%20Messages",
        r"%/Bin",
    }
    assert {"trash", "deleted messages", "bin"} == mailbox_url.TRASH_LEAVES


def test_rank_case_demotes_every_special_including_bin():
    sql = mailbox_url.rank_case("mb.url")
    for pat in (
        "%/Trash",
        r"%/Deleted\%20Messages",
        "%/Bin",
        r"%/All\%20Mail",
        "%/Archive",
        "%/Junk",
        "%/Spam",
    ):
        assert f"'{pat}'" in sql, pat
    assert "'%/INBOX'" in sql


def test_rank_case_keeps_the_anchoring_rules():
    # Final-segment anchoring: both-side wrapping ('%Junk%', '%All%Mail') demoted the
    # real user folders 'Junkyard' and 'Wallets/Old Mail'. Junk/Spam additionally take
    # the '<name>%20…' prefix form for Exchange's `Junk%20E-mail`.
    sql = mailbox_url.rank_case("mb.url")
    assert "'%Junk%'" not in sql and "'%All%Mail'" not in sql
    assert r"'%/Junk\%20%'" in sql and r"'%/Spam\%20%'" in sql
    # Trash/Archive/All Mail/Bin deliberately have NO prefix form — 'Trash bin' or
    # 'Archive 2019' are user folders.
    assert r"'%/Trash\%20%'" not in sql and r"'%/Bin\%20%'" not in sql


def test_sent_suffixes_cover_every_account_type_leaf_anchored():
    # #192: IMAP/Yahoo `Sent`, iCloud `Sent Messages`, Gmail `Sent Mail`, Exchange
    # `Sent Items` — final-segment anchored so a user folder `Sentimental` (or a
    # nested `Sent/2019`) doesn't read as a Sent mailbox.
    assert mailbox_url.SENT_SUFFIXES == (
        "%/Sent",
        r"%/Sent\%20Messages",
        r"%/Sent\%20Mail",
        r"%/Sent\%20Items",
    )
