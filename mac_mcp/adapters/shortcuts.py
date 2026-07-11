"""Shortcuts adapter — the ``shortcuts`` CLI (#22, #63). No app, no Automation prompt.

``shortcuts list --show-identifiers`` lists the user's shortcuts as ``Name (UUID)``.
``Pointer.id`` is the UUID (stable across renames), ``summary`` the name, ``deeplink``
``shortcuts://run-shortcut?id=<UUID>``. ``run_shortcut`` invokes one by name OR id (the
CLI takes ``<shortcut-name-or-identifier>``) — the one write, a gateway to every
automation the user owns — and captures real output via ``--output-path``. All args go
via argv with NO shell, so a hostile shortcut name can't inject a command (recursechat's
RCE lesson).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from ..contracts import Pointer
from ..runtime import NativeError, NativeTimeout, clean_summary, sanitize_line

MAX_SHORTCUTS = 100
MAX_OUTPUT = 280  # pointers-not-payload: cite the run + a bounded snippet of any output
_TIMEOUT = 10.0
_RUN_TIMEOUT = 30.0  # a shortcut does real work — longer than `list`

# `shortcuts list --show-identifiers` prints `Name (UUID)`; the UUID is the last
# parenthesized group, so the greedy `.*` lets a name legitimately contain "(…)". A
# strict 8-4-4-4-12 hex shape avoids mistaking a name ending in "(…)" for an id.
_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
_LINE_RE = re.compile(rf"^(?P<name>.*) \((?P<uuid>{_UUID})\)$")
_UUID_RE = re.compile(_UUID)  # a bare handle that IS a UUID (the id-first run path)


def _deeplink(uuid: str) -> str:
    # shortcuts://run-shortcut?id=<UUID> opens/runs the shortcut. A UUID is URL-safe.
    return f"shortcuts://run-shortcut?id={uuid}"


def _parse_list(stdout: str) -> list[tuple[str, str | None]]:
    """`shortcuts list --show-identifiers` → [(name, uuid|None)]. A line without the
    trailing `(UUID)` (an older CLI that ignores --show-identifiers) degrades to
    (name, None) so the adapter still works, just without a stable id/deeplink."""
    out = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        out.append((m.group("name"), m.group("uuid")) if m else (line, None))
    return out


def _list_pointer(name: str, uuid: str | None) -> Pointer:
    # id = the UUID (stable across renames) when available, else the name (degraded).
    return Pointer(
        id=uuid or name,
        summary=clean_summary(name),
        deeplink=_deeplink(uuid) if uuid else "",
    )


def _run_pointer(handle: str, output: str, display: str | None = None) -> Pointer:
    """Cite that a shortcut ran, plus a bounded snippet of any stdout it returned.

    ``id`` is the run ``handle`` (the name or UUID actually invoked); ``display`` is the
    human-readable name shown in the summary — when a run is invoked by UUID (the
    id-first path), run_shortcut resolves it to the name so the citation reads "ran
    Driving Mode", not an opaque UUID (#63 review). Defaults to ``handle`` if not given.
    """
    # The "…" ("more, amount unknown") marker keys off the RAW read length, NOT the
    # sanitized length: run_shortcut reads only MAX_OUTPUT+1 chars, and sanitize_line
    # can shrink that below MAX_OUTPUT (folding CRLF, stripping control chars) — keying
    # off the sanitized length would drop the marker even when output WAS truncated (#52
    # review). sanitize_line (not clean_body's char-count marker, which would lie about
    # how much was dropped once the read is already capped) strips the control chars /
    # ANSI a shortcut may emit (carterlasalle #2) and flattens to one citable line.
    truncated = len(output) > MAX_OUTPUT
    out = sanitize_line(output)
    summary = f"ran {sanitize_line(display if display is not None else handle)}"
    if out:
        snippet = out[:MAX_OUTPUT] + ("…" if truncated else "")
        summary = f"{summary} → {snippet}"
    return Pointer(id=handle, summary=summary, deeplink="")


def _filter_entries(
    entries: list[tuple[str, str | None]], query: str
) -> list[tuple[str, str | None]]:
    # filter by the NAME substring (not the UUID — the id is a machine handle).
    q = query.strip().lower()
    if q:
        entries = [e for e in entries if q in e[0].lower()]
    return entries[:MAX_SHORTCUTS]


class ShortcutsAdapter:
    def get_pointers(self, query: str = "") -> list[Pointer]:
        """query: optional name substring (empty lists all shortcuts)."""
        try:
            proc = subprocess.run(
                ["shortcuts", "list", "--show-identifiers"],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
        except subprocess.TimeoutExpired as e:
            raise NativeTimeout(
                f"shortcuts list didn't finish within {_TIMEOUT}s and was stopped — "
                "the Shortcuts CLI may be hung. Tell the user; do not retry "
                "immediately."
            ) from e
        if proc.returncode != 0:
            raise NativeError(f"shortcuts CLI failed: {proc.stderr.strip()}")
        entries = _filter_entries(_parse_list(proc.stdout), query)
        return [_list_pointer(name, uuid) for name, uuid in entries]

    def run_shortcut(self, name: str, input_text: str | None = None) -> Pointer:
        """Run a shortcut by name OR UUID id (the CLI takes either); optional text
        ``input_text`` piped via stdin.

        The result is written to a temp file (``--output-path``) and only a bounded
        prefix is read back, so a shortcut returning a huge blob can't balloon the
        worker's memory (best-effort; some shortcuts return nothing). The Pointer cites
        the run + a truncated snippet, never a full payload.
        """
        name = name.strip()
        if not name:
            raise ValueError("run_shortcut needs a shortcut name (got an empty name)")
        with tempfile.TemporaryDirectory(prefix="mac-mcp-shortcut-") as tmp:
            # ponytail: --output-path bounds *memory* (we read back only a snippet,
            # see below), not disk — a huge result writes fully here first. Fine: the
            # dir is torn down on block exit and the write is capped by _RUN_TIMEOUT.
            # Add an os.path.getsize guard before the read if disk pressure shows up.
            out_path = os.path.join(tmp, "out")
            # Options FIRST, then `--`, then the name LAST (#63 review): `--` stops
            # option scanning so a shortcut literally named "-i"/"--help" is the name,
            # not a flag (arg confusion, not shell injection — argv-only). Verified on
            # the real CLI: `shortcuts run --output-path X -- <name>` treats <name> as
            # the shortcut; the name must come AFTER `--`, options before it.
            cmd = ["shortcuts", "run", "--output-path", out_path]
            if input_text is not None:
                cmd += ["--input-path", "-"]
            cmd += ["--", name]
            try:
                proc = subprocess.run(
                    cmd,
                    input=input_text,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=_RUN_TIMEOUT,
                )
            except subprocess.TimeoutExpired as e:
                raise NativeTimeout(
                    f"the shortcut didn't finish within {_RUN_TIMEOUT}s and was "
                    "stopped — it may have partially run; check its effects before "
                    "retrying. Do not retry immediately."
                ) from e
            if proc.returncode != 0:
                raise NativeError(
                    f"shortcuts CLI failed: shortcuts run {name!r}: "
                    f"{proc.stderr.strip()}"
                )
            try:
                # errors="replace": a non-text result (image/file) must not crash the
                # decode; read only a snippet, never the whole payload.
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    output = f.read(MAX_OUTPUT + 1)
            except (FileNotFoundError, IsADirectoryError):
                output = ""  # no usable result file (none written, or a dir not a file)
        # cite the human-readable name even when invoked by UUID (#63 review)
        return _run_pointer(name, output, display=self._display_name(name))

    def _display_name(self, handle: str) -> str:
        """A human-readable name for the run citation. If `handle` is a UUID (the
        id-first path), resolve it to its name via one `list` call — best-effort: on any
        failure just cite the handle. Otherwise the handle already IS the name."""
        if not _UUID_RE.fullmatch(handle.strip()):
            return handle
        try:
            proc = subprocess.run(
                ["shortcuts", "list", "--show-identifiers"],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            if proc.returncode == 0:
                for name, uuid in _parse_list(proc.stdout):
                    if uuid and uuid.lower() == handle.strip().lower():
                        return name
        except (subprocess.TimeoutExpired, OSError):
            pass
        return handle
