"""Pytest plugin that tries the WR-01 fix: both TCC db constants (and doctor's frozen
``_FDA_PATHS`` copy) point at absent paths for the whole session.

Run: PYTHONPATH=<this dir> uv run pytest -q -p tcc_absent
"""

import pytest

from macos_apps_mcp import deploy, doctor


@pytest.fixture(autouse=True, scope="session")
def _tcc_absent(tmp_path_factory):
    root = tmp_path_factory.mktemp("no-tcc")
    user, system = root / "user" / "TCC.db", root / "system" / "TCC.db"
    mp = pytest.MonkeyPatch()
    mp.setattr(deploy, "_TCC_DB", user)
    mp.setattr(deploy, "_TCC_SYSTEM_DB", system)
    mp.setattr(doctor, "_FDA_PATHS", (user, system))
    yield
    mp.undo()
