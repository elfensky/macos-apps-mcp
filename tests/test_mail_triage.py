"""Unit tests for mail triage — pure classifiers over fixtures (no TCC)."""

from __future__ import annotations

from macos_apps_mcp.adapters.mail import _classify_needs_response

ME = {"me@x.com"}


def _rec(**kw):
    base = {
        "id": "<m1@x>",
        "subject": "Hi",
        "sender": "bob@y.com",
        "to_addrs": ["me@x.com"],
        "secs_ago": 100,
        "was_replied_to": False,
        "read": False,
        "flagged": False,
    }
    base.update(kw)
    return base


def test_needs_response_drops_replied():
    out = _classify_needs_response([_rec(was_replied_to=True)], ME)
    assert out == []


def test_needs_response_drops_non_direct():
    # I'm not in to_addrs (cc-only / bulk) → dropped
    out = _classify_needs_response([_rec(to_addrs=["someone@else.com"])], ME)
    assert out == []


def test_needs_response_tiers_and_reasons():
    recs = [
        _rec(id="<f@x>", flagged=True, read=True),  # flagged wins even if read
        _rec(id="<u@x>", read=False),  # unread-direct
        _rec(id="<a@x>", read=True),  # unanswered-direct
    ]
    out = _classify_needs_response(recs, ME)
    assert [(p.id, p.reason) for p in out] == [
        ("<f@x>", "flagged"),
        ("<u@x>", "unread-direct"),
        ("<a@x>", "unanswered-direct"),
    ]


def test_needs_response_recency_tiebreak_within_tier():
    recs = [
        _rec(id="<old@x>", read=False, secs_ago=900),
        _rec(id="<new@x>", read=False, secs_ago=10),
    ]
    out = _classify_needs_response(recs, ME)
    assert [p.id for p in out] == ["<new@x>", "<old@x>"]  # most recent first


def test_needs_response_empty_my_addrs_degrades_to_flagged_only():
    recs = [_rec(id="<f@x>", flagged=True), _rec(id="<u@x>", read=False)]
    out = _classify_needs_response(recs, set())
    assert [p.id for p in out] == ["<f@x>"]  # flagged only, no flood


def test_needs_response_bounded():
    recs = [_rec(id=f"<m{i}@x>", read=False, secs_ago=i) for i in range(40)]
    assert len(_classify_needs_response(recs, ME)) == 25
