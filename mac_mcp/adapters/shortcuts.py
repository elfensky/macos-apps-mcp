"""Shortcuts adapter — the ``shortcuts`` CLI (#22). No app, no Automation prompt.

``shortcuts list`` enumerates the user's shortcuts; an optional query filters by name.
``Pointer.id``/``summary`` are the shortcut name; ``deeplink`` empty (the name is the
handle). ``run_shortcut`` invokes one by name (``shortcuts run``) — the one write, a
gateway to every automation the user owns.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from ..contracts import Pointer
from ..runtime import NativeError, NativeTimeout

MAX_SHORTCUTS = 100
MAX_OUTPUT = 280  # pointers-not-payload: cite the run + a bounded snippet of any output
_TIMEOUT = 10.0
_RUN_TIMEOUT = 30.0  # a shortcut does real work — longer than `list`


def _pointer(name: str) -> Pointer:
    return Pointer(id=name, summary=name, deeplink="")


def _run_pointer(name: str, output: str) -> Pointer:
    """Cite that a shortcut ran, plus a bounded snippet of any stdout it returned."""
    out = output.strip()
    summary = f"ran {name}"
    if out:
        snippet = out if len(out) <= MAX_OUTPUT else out[:MAX_OUTPUT] + "…"
        summary = f"{summary} → {snippet}"
    return Pointer(id=name, summary=summary, deeplink="")


def _filter_names(names: list[str], query: str) -> list[str]:
    q = query.strip().lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:MAX_SHORTCUTS]


class ShortcutsAdapter:
    def get_pointers(self, query: str = "") -> list[Pointer]:
        """query: optional name substring (empty lists all shortcuts)."""
        try:
            proc = subprocess.run(
                ["shortcuts", "list"], capture_output=True, text=True, timeout=_TIMEOUT
            )
        except subprocess.TimeoutExpired as e:
            raise NativeTimeout(
                f"shortcuts list didn't finish within {_TIMEOUT}s and was stopped — "
                "the Shortcuts CLI may be hung. Tell the user; do not retry "
                "immediately."
            ) from e
        if proc.returncode != 0:
            raise NativeError(f"shortcuts CLI failed: {proc.stderr.strip()}")
        names = [n for n in proc.stdout.splitlines() if n.strip()]
        return [_pointer(n) for n in _filter_names(names, query)]

    def run_shortcut(self, name: str, input_text: str | None = None) -> Pointer:
        """Run a shortcut by exact name; optional text ``input_text`` piped via stdin.

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
            cmd = ["shortcuts", "run", name, "--output-path", out_path]
            if input_text is not None:
                cmd += ["--input-path", "-"]
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
        return _run_pointer(name, output)
