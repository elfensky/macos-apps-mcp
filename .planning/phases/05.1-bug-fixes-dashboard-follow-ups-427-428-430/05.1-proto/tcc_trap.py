"""Pytest plugin that lists the tests touching the developer's real TCC databases (WR-01).

Run: PYTHONPATH=<this dir> TCC_TRAP_OUT=<file> uv run pytest -q -p tcc_trap
It wraps ``deploy._tcc_rows`` and ``doctor._fda_surface`` (the two readers) and records
``PYTEST_CURRENT_TEST`` whenever they are about to read a real TCC.db path. Read-only:
it calls the original function unchanged.
"""

import functools
import os

from macos_apps_mcp import deploy, doctor

REAL = {str(deploy._TCC_DB), str(deploy._TCC_SYSTEM_DB)}
HITS: dict[str, set[str]] = {}


def _note(kind: str) -> None:
    HITS.setdefault(os.environ.get("PYTEST_CURRENT_TEST", "?").split(" ")[0], set()).add(kind)


_orig_rows = deploy._tcc_rows


@functools.wraps(_orig_rows)
def _rows(db, wanted):
    if str(db) in REAL:
        _note("deploy._tcc_rows")
    return _orig_rows(db, wanted)


deploy._tcc_rows = _rows

_orig_fda = doctor._fda_surface


@functools.wraps(_orig_fda)
def _fda():
    if any(str(p) in REAL for p in doctor._FDA_PATHS):
        _note("doctor._fda_surface")
    return _orig_fda()


doctor._fda_surface = _fda


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("TCC_TRAP_OUT")
    if out:
        with open(out, "w") as f:
            for t in sorted(HITS):
                f.write(f"{t}\t{','.join(sorted(HITS[t]))}\n")
