"""Pytest configuration for test suite."""

from __future__ import annotations

import tempfile
from pathlib import Path


def pytest_configure(config):
    """Configure pytest to use a shorter basetemp path for Unix domain socket
    compatibility on macOS (~104-byte limit for AF_UNIX paths)."""
    if not config.option.basetemp:
        config.option.basetemp = Path(tempfile.gettempdir()) / "mp"
