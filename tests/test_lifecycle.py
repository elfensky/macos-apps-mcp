"""Unit tests for lifecycle.py — orphan detection (#56). The child-termination
half lives in test_runtime.py with the child registry it exercises.
"""

from __future__ import annotations

import os

from macos_apps_mcp.lifecycle import _parent_died


def test_parent_died_false_when_ppid_unchanged():
    # our real parent is alive and unchanged → not orphaned.
    assert _parent_died(os.getppid()) is False


def test_parent_died_true_when_reparented():
    # getppid() no longer equals the launch-time pid → parent gone, we're orphaned.
    assert _parent_died(os.getppid() + 999_999) is True
