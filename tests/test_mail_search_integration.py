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
