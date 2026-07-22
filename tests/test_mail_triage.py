"""Unit tests for mail triage — pure classifiers over fixtures (no TCC)."""

from __future__ import annotations

from macos_apps_mcp.adapters.mail import (
    _classify_awaiting_reply,
    _classify_needs_response,
    _norm_mid,
    _parse_my_addrs,
    _parse_sent_records,
    _parse_triage_records,
    _referenced_ids,
)

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


DAY = 86400


def _sent(**kw):
    base = {
        "id": "<s1@x>",
        "subject": "Proposal",
        "recipient_addrs": ["bob@y.com"],
        "secs_ago": 5 * DAY,
    }
    base.update(kw)
    return base


def test_norm_mid():
    assert _norm_mid("<Abc@X>") == "abc@x"
    assert _norm_mid(" abc@x ") == "abc@x"


def test_referenced_ids_parses_folded_headers():
    blob = (
        "From: a@b.com\r\n"
        "In-Reply-To: <s1@x>\r\n"
        "References: <root@x>\r\n <s1@x>\r\n"  # folded continuation
        "Subject: Re: Proposal\r\n\r\n"
    )
    assert _referenced_ids([blob]) == {"s1@x", "root@x"}


def test_awaiting_reply_suppressed_when_id_referenced():
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"s1@x"}, days=3)
    assert out == []


def test_awaiting_reply_emitted_when_not_referenced():
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"other@x"}, days=3)
    assert [p.id for p in out] == ["<s1@x>"]
    assert out[0].reason == "awaiting-reply"


def test_awaiting_reply_same_subject_no_ref_does_not_suppress():
    # threading is by id, not subject: a same-subject reply that doesn't cite s1 → still
    # awaiting
    out = _classify_awaiting_reply([_sent(id="<s1@x>")], {"unrelated@x"}, days=3)
    assert [p.id for p in out] == ["<s1@x>"]


def test_awaiting_reply_days_threshold_excludes_recent():
    out = _classify_awaiting_reply([_sent(secs_ago=1 * DAY)], set(), days=3)
    assert out == []  # sent 1 day ago, threshold 3 days


def test_awaiting_reply_oldest_first():
    recs = [_sent(id="<a@x>", secs_ago=4 * DAY), _sent(id="<b@x>", secs_ago=9 * DAY)]
    out = _classify_awaiting_reply(recs, set(), days=3)
    assert [p.id for p in out] == ["<b@x>", "<a@x>"]  # most overdue first


US = "\x1f"
RS = "\x1e"


def test_parse_triage_records():
    raw = (
        US.join(
            [
                "<m1@x>",
                "Hi",
                "bob@y.com",
                "me@x.com,also@x.com",
                "120",
                "false",
                "true",
                "false",
            ]
        )
        + RS
    )
    recs = _parse_triage_records(raw)
    assert recs == [
        {
            "id": "<m1@x>",
            "subject": "Hi",
            "sender": "bob@y.com",
            "to_addrs": ["me@x.com", "also@x.com"],
            "secs_ago": 120,
            "was_replied_to": False,
            "read": True,
            "flagged": False,
        }
    ]


def test_parse_triage_skips_malformed():
    assert _parse_triage_records("") == []
    assert _parse_triage_records("only" + US + "two" + RS) == []  # too few fields


def test_parse_sent_records():
    raw = US.join(["<s1@x>", "Proposal", "bob@y.com,carol@z.com", "432000"]) + RS
    assert _parse_sent_records(raw) == [
        {
            "id": "<s1@x>",
            "subject": "Proposal",
            "recipient_addrs": ["bob@y.com", "carol@z.com"],
            "secs_ago": 432000,
        }
    ]


def test_parse_my_addrs_lowercases():
    addrs = _parse_my_addrs("Me@X.com" + US + "you@y.com" + US)
    assert addrs == {"me@x.com", "you@y.com"}
