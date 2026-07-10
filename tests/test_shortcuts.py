"""Unit tests for the shortcuts adapter — pure mapping/filtering + run dispatch.

The mapping/filter helpers run with no CLI; ``run_shortcut`` is tested by faking
``subprocess.run`` at the module boundary (no real shortcut executed).
"""

from __future__ import annotations

import subprocess

import pytest

from mac_mcp.adapters.shortcuts import (
    MAX_OUTPUT,
    MAX_SHORTCUTS,
    ShortcutsAdapter,
    _filter_names,
    _pointer,
    _run_pointer,
)
from mac_mcp.contracts import Pointer


def _fake_run(monkeypatch, *, returncode=0, stdout="", stderr=""):
    """Swap shortcuts.subprocess.run for a fake; return a dict capturing the call.

    Mirrors ``shortcuts run --output-path <file>``: the fake writes ``stdout`` to that
    path on success, so the adapter reads the result back like the CLI delivers it.
    """
    seen: dict = {}

    def fake(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        if returncode == 0 and "--output-path" in cmd:
            with open(cmd[cmd.index("--output-path") + 1], "w", encoding="utf-8") as f:
                f.write(stdout)
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)

    monkeypatch.setattr("mac_mcp.adapters.shortcuts.subprocess.run", fake)
    return seen


def test_pointer():
    p = _pointer("Track water")
    assert isinstance(p, Pointer)
    assert p.id == "Track water" and p.summary == "Track water" and p.deeplink == ""


def test_filter_substring_case_insensitive():
    names = ["Driving Mode", "Track water", "Open with Opener"]
    assert _filter_names(names, "track") == ["Track water"]


def test_filter_empty_returns_all():
    assert _filter_names(["a", "b"], "  ") == ["a", "b"]


def test_filter_caps_at_max():
    big = [str(i) for i in range(MAX_SHORTCUTS + 10)]
    assert len(_filter_names(big, "")) == MAX_SHORTCUTS


def test_run_pointer_no_output():
    p = _run_pointer("Driving Mode", "")
    assert p.id == "Driving Mode"
    assert p.summary == "ran Driving Mode" and p.deeplink == ""


def test_run_pointer_with_output():
    assert _run_pointer("Weather", "  72F sunny  ").summary == "ran Weather → 72F sunny"


def test_run_pointer_truncates_long_output():
    p = _run_pointer("Dump", "x" * (MAX_OUTPUT + 50))
    assert p.summary.endswith("…")
    assert len(p.summary) <= len("ran Dump → ") + MAX_OUTPUT + 1


def test_run_shortcut_decodes_leniently(monkeypatch):
    # the hardening: a non-text stdout must never crash the decode
    seen = _fake_run(monkeypatch, stdout="ok")
    p = ShortcutsAdapter().run_shortcut("Weather")
    assert seen["kw"].get("errors") == "replace"
    assert "--output-path" in seen["cmd"] and "--input-path" not in seen["cmd"]
    assert p.summary == "ran Weather → ok"


def test_run_shortcut_pipes_input(monkeypatch):
    seen = _fake_run(monkeypatch, stdout="done")
    ShortcutsAdapter().run_shortcut("Append Note", "hello")
    assert "--input-path" in seen["cmd"] and seen["kw"].get("input") == "hello"


def test_run_shortcut_reads_output_bounded(monkeypatch):
    # finding-8 fix: a huge result is read only up to a snippet, never fully buffered.
    _fake_run(monkeypatch, stdout="x" * (MAX_OUTPUT * 100))
    p = ShortcutsAdapter().run_shortcut("Dump")
    assert p.summary.endswith("…")
    assert len(p.summary) <= len("ran Dump → ") + MAX_OUTPUT + 1


def test_run_shortcut_tolerates_directory_output(monkeypatch):
    # a shortcut whose --output-path lands a directory (not a file) must not crash the
    # worker: open() raises IsADirectoryError, which maps to "no usable result", same as
    # a missing file.
    import os

    def fake(cmd, **kw):
        os.mkdir(cmd[cmd.index("--output-path") + 1])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("mac_mcp.adapters.shortcuts.subprocess.run", fake)
    assert ShortcutsAdapter().run_shortcut("Folder").summary == "ran Folder"


def test_run_shortcut_raises_on_nonzero(monkeypatch):
    _fake_run(monkeypatch, returncode=1, stderr="no such shortcut")
    with pytest.raises(RuntimeError, match="shortcuts run"):
        ShortcutsAdapter().run_shortcut("Nope")


def test_run_shortcut_rejects_empty_name(monkeypatch):
    _fake_run(monkeypatch)  # never reached — empty name fails first
    with pytest.raises(ValueError, match="needs a shortcut name"):
        ShortcutsAdapter().run_shortcut("   ")


def test_pointer_summary_is_sanitized_but_id_stays_raw():
    # #52 routing: the display summary is control-stripped, but id must stay the EXACT
    # name (the run handle), so run-by-name still works for an oddly-named shortcut.
    p = _pointer("Back\x07up")
    assert p.summary == "Backup"
    assert p.id == "Back\x07up"  # handle preserved verbatim


def test_run_pointer_sanitizes_output_control_chars():
    # #52: a shortcut's stdout can carry control chars/ANSI — stripped from the summary.
    p = _run_pointer("Greet", "hello\x07\tworld")
    assert p.summary == "ran Greet → hello world"


def test_run_pointer_ellipsis_keys_off_raw_length_not_sanitized():
    # #52 review (finding 4): run_shortcut reads only MAX_OUTPUT+1 chars; sanitize_line
    # folds CRLFs so the sanitized snippet drops BELOW MAX_OUTPUT even when the read was
    # truncated. The "…" marker must still appear (keyed off the RAW length). The old
    # `len(sanitized) <= MAX_OUTPUT` check would have wrongly dropped it.
    raw = ("line\r\n" * 80)[: MAX_OUTPUT + 1]  # > MAX_OUTPUT raw, folds much shorter
    p = _run_pointer("Backup", raw)
    assert p.summary.endswith("…")
    # sanity: the sanitized snippet is really shorter than MAX_OUTPUT (old logic broke)
    assert len(p.summary) < len("ran Backup → ") + MAX_OUTPUT
