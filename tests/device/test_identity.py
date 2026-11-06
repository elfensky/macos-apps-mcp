"""Read-only identity checks of the installed daemon (#574, #575, #576, #580)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.device

NONE = "zz-macos-apps-mcp-no-such-text"


def test_doctor_names_version_and_build(guard):
    err, d, text, secs = guard.run("doctor", request=False)
    d = d if isinstance(d, dict) else {}
    ok = not err and bool(d.get("version")) and bool(d.get("build"))
    assert ok, (
        f"error={err} version={d.get('version')} build={d.get('build')} {text[:200]}"
    )


def test_audit_has_no_error_entry(guard):
    err, rows, text, secs = guard.run("audit")
    bad = sum(1 for r in rows or [] if isinstance(r, dict) and "error" in r)
    assert not err and bad == 0, f"error={err} error_entries={bad} {text[:200]}"


def test_usage_has_its_three_keys(guard):
    err, d, text, secs = guard.run("usage")
    keys = {"tools", "never_used", "total_calls"} & set(
        d if isinstance(d, dict) else ()
    )
    assert not err and len(keys) == 3, f"error={err} keys={sorted(keys)} {text[:200]}"


def test_messages_search_without_a_match_answers(guard):
    err, rows, text, secs = guard.run("messages_search", query=NONE, limit=40)
    n = len(rows) if isinstance(rows, list) else None
    assert not err and n == 0, f"error={err} count={n} secs={secs} {text[:200]}"


def test_ps_parse_in_a_comma_decimal_locale():
    # A subprocess: the suite conftest refuses tracked_run in this process.
    code = (
        "import json; from macos_apps_mcp import runtime;"
        "print(json.dumps(runtime.app_process_info('Finder')))"
    )
    env = {**os.environ, "LC_ALL": "nl_BE.UTF-8"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    info = json.loads(out.stdout or "null") if out.returncode == 0 else None
    cpu = info.get("cpu") if isinstance(info, dict) else None
    assert isinstance(cpu, float), f"exit={out.returncode} cpu={type(cpu).__name__}"
