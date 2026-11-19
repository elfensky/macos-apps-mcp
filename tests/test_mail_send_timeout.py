"""#573: a send that times out must not tell the agent to retry.

Stopping ``osascript`` does not recall an Apple Event that Mail accepted, so a host
timeout on a script that holds ``send`` may still deliver the mail. The error must say
so, and must never carry the generic "retry" advice of ``runtime.run_osascript``.
"""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail_outgoing
from macos_apps_mcp.errors import AutomationDenied, NativeTimeout
from macos_apps_mcp.text import RS, US

_GENERIC = (
    "osascript timed out after 120s. Tell the user to dismiss any stuck prompt, "
    "then retry with a narrower query. Wait a minute, then retry once."
)


def _draft_payload():
    return US.join(
        ["Subj", "Me <me@x>", "to@x" + RS, "", "", "0", "0", "approved body"]
    )


def _builders():
    return {
        "new_message": lambda: mail_outgoing.new_message("to@x", "Hi", "body"),
        "forward_of": lambda: mail_outgoing.forward_of("<m@x>", "INBOX", "to@x"),
        "stored_draft": lambda: mail_outgoing.stored_draft("<d@x>"),
    }


def _fake(error, calls):
    def fake(script, *argv, **kw):
        if script is mail_outgoing._DRAFT_ENVELOPE:
            return _draft_payload()
        calls.append((script, kw.get("timeout")))
        raise error

    return fake


@pytest.fixture
def _seams(monkeypatch):
    monkeypatch.setattr(runtime, "body_file", lambda text: nullcontext("/tmp/fake"))


@pytest.mark.parametrize("name", ["new_message", "forward_of", "stored_draft"])
def test_send_timeout_warns_and_never_says_retry(monkeypatch, _seams, name):
    calls = []
    monkeypatch.setattr(runtime, "run_osascript", _fake(NativeTimeout(_GENERIC), calls))
    outgoing = _builders()[name]()
    with pytest.raises(NativeTimeout) as info:
        mail_outgoing.deliver(outgoing, dry_run=False)
    text = str(info.value)
    assert "MAY have been sent" in text
    assert "Outbox" in text and "Sent" in text
    assert "narrower query" not in text
    assert "retry once" not in text
    assert isinstance(info.value.__cause__, NativeTimeout)
    assert len(calls) == 1  # one dispatch, no _OUTBOX_COUNT after a failed send


@pytest.mark.parametrize("name", ["new_message", "stored_draft"])
def test_send_script_host_limit_equals_its_own_limit(monkeypatch, _seams, name):
    calls = []
    monkeypatch.setattr(runtime, "run_osascript", _fake(NativeTimeout(_GENERIC), calls))
    with pytest.raises(NativeTimeout):
        mail_outgoing.deliver(_builders()[name](), dry_run=False)
    assert calls == [(mail_outgoing._SEND, 120.0)]


@pytest.mark.parametrize("name", ["new_message", "forward_of", "stored_draft"])
def test_automation_denied_passes_through_unchanged(monkeypatch, _seams, name):
    denied = AutomationDenied("Mail: automation not granted")
    monkeypatch.setattr(runtime, "run_osascript", _fake(denied, []))
    with pytest.raises(AutomationDenied) as info:
        mail_outgoing.deliver(_builders()[name](), dry_run=False)
    assert info.value is denied


@pytest.mark.parametrize("name", ["new_message", "forward_of"])
def test_dry_run_makes_no_native_call(monkeypatch, name):
    def fake(*a, **k):
        raise AssertionError("a dry run must make no native call")

    monkeypatch.setattr(runtime, "run_osascript", fake)
    out = mail_outgoing.deliver(_builders()[name](), dry_run=True)
    assert "sent" not in out
