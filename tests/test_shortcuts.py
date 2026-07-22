"""Unit tests for the shortcuts adapter — pure mapping/filtering + run dispatch.

The mapping/filter helpers run with no CLI; ``run_shortcut`` is tested by faking
``subprocess.run`` at the module boundary (no real shortcut executed).
"""

from __future__ import annotations

import subprocess

import pytest

from macos_apps_mcp.adapters.shortcuts import (
    MAX_OUTPUT,
    MAX_SHORTCUTS,
    ShortcutsAdapter,
    _deeplink,
    _filter_entries,
    _list_pointer,
    _parse_list,
    _run_pointer,
)
from macos_apps_mcp.contracts import Pointer

_UUID = "40AE7C31-B301-4488-889D-44DB6E8FF542"


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

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", fake)
    return seen


def test_list_pointer_uuid_is_stable_id():
    # #63: id = the UUID (survives renames), summary = the name, deeplink = shortcuts://.
    p = _list_pointer("Track water", _UUID)
    assert isinstance(p, Pointer)
    assert p.id == _UUID  # stable across a rename — the whole point
    assert p.summary == "Track water"
    assert p.deeplink == f"shortcuts://run-shortcut?id={_UUID}"


def test_list_pointer_degrades_without_uuid():
    # an older CLI with no identifier → id falls back to the name, no deeplink.
    p = _list_pointer("Track water", None)
    assert p.id == "Track water" and p.deeplink == ""


def test_deeplink():
    assert _deeplink(_UUID) == f"shortcuts://run-shortcut?id={_UUID}"


def test_parse_list_name_and_uuid():
    out = _parse_list(f"Driving Mode ({_UUID})\nTrack water ({_UUID})\n")
    assert out == [("Driving Mode", _UUID), ("Track water", _UUID)]


def test_parse_list_name_with_parens():
    # the UUID is the LAST parenthesized group, so a name with "(…)" is kept whole.
    out = _parse_list(f"My (Cool) Shortcut ({_UUID})\n")
    assert out == [("My (Cool) Shortcut", _UUID)]


def test_parse_list_degrades_on_missing_identifier():
    # a line without a trailing (UUID) (old CLI) → (name, None), still usable.
    assert _parse_list("Just A Name\n") == [("Just A Name", None)]
    # a trailing paren that is NOT a UUID is part of the name, not an id.
    assert _parse_list("Weird (not a uuid)\n") == [("Weird (not a uuid)", None)]


def test_filter_substring_case_insensitive():
    entries = [("Driving Mode", "u1"), ("Track water", "u2"), ("Open", "u3")]
    assert _filter_entries(entries, "track") == [("Track water", "u2")]


def test_filter_folds_diacritics_and_smart_punctuation():
    # #64: an ASCII query finds a diacritic/smart-punctuation shortcut name.
    entries = [("Café timer", "u1"), ("Andrei’s macro", "u2"), ("Plain", "u3")]
    assert _filter_entries(entries, "cafe") == [("Café timer", "u1")]
    assert _filter_entries(entries, "andrei's") == [("Andrei’s macro", "u2")]


def test_filter_diacritic_only_query_folds_to_empty_lists_all():
    # #64 review: "¨" folds to a bare space — it must NOT become a "contains-a-space"
    # filter (which would drop single-word names). Folding to empty → list-all, matching
    # the empty-query semantics and the notes.get_pointers guard.
    entries = [("Timer", "u1"), ("Café timer", "u2"), ("Plain", "u3")]
    assert _filter_entries(entries, "¨") == entries


def test_filter_empty_returns_all():
    assert _filter_entries([("a", "u"), ("b", None)], "  ") == [("a", "u"), ("b", None)]


def test_filter_caps_at_max():
    big = [(str(i), None) for i in range(MAX_SHORTCUTS + 10)]
    assert len(_filter_entries(big, "")) == MAX_SHORTCUTS


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

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", fake)
    assert ShortcutsAdapter().run_shortcut("Folder").summary == "ran Folder"


def test_run_shortcut_raises_on_nonzero(monkeypatch):
    _fake_run(monkeypatch, returncode=1, stderr="no such shortcut")
    with pytest.raises(RuntimeError, match="shortcuts run"):
        ShortcutsAdapter().run_shortcut("Nope")


def test_run_shortcut_rejects_empty_name(monkeypatch):
    _fake_run(monkeypatch)  # never reached — empty name fails first
    with pytest.raises(ValueError, match="needs a shortcut name"):
        ShortcutsAdapter().run_shortcut("   ")


def test_list_pointer_summary_sanitized_uuid_id():
    # #52 + #63: the display summary is control-stripped; with a UUID the id is the
    # clean UUID (an oddly-named shortcut runs by its stable id, not the raw name).
    p = _list_pointer("Back\x07up", _UUID)
    assert p.summary == "Backup" and p.id == _UUID


def test_list_pointer_degraded_id_stays_raw_name():
    # without a UUID the name IS the run handle, so it stays EXACT (run-by-name works
    # for an oddly-named shortcut) even though the summary is sanitized.
    p = _list_pointer("Back\x07up", None)
    assert p.summary == "Backup" and p.id == "Back\x07up"


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


# --- get_pointers over --show-identifiers + injection safety (#63) --------------------


def test_get_pointers_uses_show_identifiers_and_maps_uuid(monkeypatch):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        u2 = "FE0E0CDE-B2B0-4D6F-BF5C-DD64912317E9"
        out = f"Driving Mode ({_UUID})\nTrack water ({u2})\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", fake)
    ptrs = ShortcutsAdapter().get_pointers("driving")  # filters by NAME
    assert "--show-identifiers" in seen["cmd"]
    assert len(ptrs) == 1
    assert ptrs[0].id == _UUID  # UUID, not the name
    assert ptrs[0].summary == "Driving Mode"
    assert ptrs[0].deeplink == f"shortcuts://run-shortcut?id={_UUID}"


def test_run_shortcut_by_uuid_resolves_name_for_citation(monkeypatch):
    # id-first: run accepts the UUID (one argv element), AND the citation resolves the
    # UUID back to its human name via one `list` call — "ran Driving Mode", not the UUID
    # (#63 review). Distinguishes the run call from the resolver's list call.
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        if "run" in cmd and "--output-path" in cmd:  # the run call
            with open(cmd[cmd.index("--output-path") + 1], "w", encoding="utf-8") as f:
                f.write("done")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, f"Driving Mode ({_UUID})\n", "")

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", fake)
    p = ShortcutsAdapter().run_shortcut(_UUID)
    run_cmd = next(c for c in calls if "run" in c)
    assert _UUID in run_cmd and p.id == _UUID  # ran by the UUID, id is the UUID
    assert p.summary == "ran Driving Mode → done"  # resolved to the human name


def test_run_shortcut_dash_name_after_double_dash(monkeypatch):
    # #63 review: a shortcut literally named like a flag ("--help", "-i") must be the
    # NAME, not parsed as an option. Options come first, then `--`, then the name LAST.
    seen = _fake_run(monkeypatch, stdout="")
    ShortcutsAdapter().run_shortcut("--help")
    cmd = seen["cmd"]
    assert cmd[-2:] == ["--", "--help"]  # name is last, after the -- separator
    assert cmd.index("--") > cmd.index("--output-path")  # options precede the separator


def test_run_shortcut_hostile_name_is_a_single_argv_element(monkeypatch):
    # the RCE lesson: a hostile name must be ONE argv element with NO shell — never
    # interpreted as a command (no shell=True, no interpolation).
    hostile = '; rm -rf ~ & echo "$(whoami)"'
    seen = _fake_run(monkeypatch, stdout="")
    ShortcutsAdapter().run_shortcut(hostile)
    assert hostile in seen["cmd"]  # verbatim, as a single element
    assert seen["kw"].get("shell") in (None, False)  # never shell=True


def test_get_pointers_nonzero_raises_native_error(monkeypatch):
    monkeypatch.setattr(
        "macos_apps_mcp.adapters.shortcuts.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"),
    )
    from macos_apps_mcp.errors import NativeError

    with pytest.raises(NativeError, match="shortcuts CLI failed"):
        ShortcutsAdapter().get_pointers()


def test_get_pointers_timeout_raises_native_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", boom)
    from macos_apps_mcp.errors import NativeTimeout

    with pytest.raises(NativeTimeout, match="didn't finish"):
        ShortcutsAdapter().get_pointers()


def test_run_shortcut_timeout_raises_native_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr("macos_apps_mcp.adapters.shortcuts.subprocess.run", boom)
    from macos_apps_mcp.errors import NativeTimeout

    with pytest.raises(NativeTimeout, match="didn't finish"):
        ShortcutsAdapter().run_shortcut("Slow")


def test_get_pointers_no_shell(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "macos_apps_mcp.adapters.shortcuts.subprocess.run",
        lambda cmd, **kw: (
            seen.update(cmd=cmd, kw=kw) or subprocess.CompletedProcess(cmd, 0, "", "")
        ),
    )
    ShortcutsAdapter().get_pointers()
    assert seen["kw"].get("shell") in (None, False)
