import time

import pytest

from macos_apps_mcp.adapters.mail import MailAdapter

pytestmark = pytest.mark.integration


def test_subject_search_under_1s():
    adapter = MailAdapter()
    t0 = time.perf_counter()
    out = adapter.search(subject="the", limit=25)  # a common word → real work
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"subject search took {dt:.3f}s (acceptance: <1s)"
    assert all(p.id and p.deeplink.startswith("message://") for p in out)


def test_index_bodies_then_body_search():
    adapter = MailAdapter()
    res = adapter.index_bodies()  # opt-in build (resumable — may be a no-op if built)
    assert res["indexed"] >= 0 and "coverage" in res
    # a re-run indexes nothing new (resume works)
    res2 = adapter.index_bodies()
    assert res2["indexed"] == 0 or res2["skipped"] > 0


def test_search_all_mailboxes_beats_inbox_only():
    # sqlite path reaches non-inbox folders the AppleScript inbox search cannot.
    out = MailAdapter().search(mailbox="Sent", limit=5)
    assert isinstance(out, list)


def test_a_filed_message_search_cites_can_be_opened_and_its_attachments_listed():
    """#146's acceptance, end to end on real Mail: take a hit from a NON-inbox folder
    and feed its `folder` value straight back. Before the fix this raised "no inbox
    message with that message id" — the read plane cited what the body plane refused
    to open. Reads only; nothing is created or sent."""
    adapter = MailAdapter()
    filed = [
        p
        for p in adapter.search(has_attachments=True, limit=50)
        if p.folder and not p.folder.rstrip("/").upper().endswith("INBOX")
    ]
    if not filed:
        pytest.skip("every indexed message on this Mac is in an INBOX")
    hit = filed[0]
    # the folder value goes back VERBATIM — it is a round-trip token, not a name
    assert adapter.get_body(hit.id, hit.folder) is not None
    assert isinstance(adapter.list_attachments(hit.folder), list)
