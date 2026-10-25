"""Off macOS the server must still load and list its tools, and refuse native calls.

Glama's build check starts the server in a Linux container and reads tools/list, so no
module may need a macOS framework at import. Past that, every native door refuses with
one typed error (``UnsupportedPlatform``) instead of an AttributeError or a misleading
"store not found". The platform is faked AFTER the third-party imports: faking it
earlier breaks ``sysconfig``.
"""

from __future__ import annotations

import sys

import pytest
from fastmcp.exceptions import ToolError

from macos_apps_mcp import doctor, eventkit, runtime, server
from macos_apps_mcp.errors import NativeError, UnsupportedPlatform

# The real seam functions, bound before conftest's autouse fake replaces them.
_REAL_RUN_OSASCRIPT = runtime.run_osascript
_REAL_TRACKED_RUN = runtime.tracked_run


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


def test_unsupported_platform_is_a_native_error_with_its_own_kind():
    assert issubclass(UnsupportedPlatform, NativeError)
    assert UnsupportedPlatform.kind == "unsupported_platform"


def test_require_macos_is_silent_on_the_real_platform():
    if sys.platform == "darwin":
        assert runtime.require_macos() is None


def test_require_macos_names_the_platform(linux):
    with pytest.raises(UnsupportedPlatform) as ei:
        runtime.require_macos()
    assert "runs only on macOS" in str(ei.value)
    assert "running on linux" in str(ei.value)


def test_run_native_refuses_and_never_runs_the_callable(linux):
    def boom():
        raise AssertionError("the callable must not run off macOS")

    with pytest.raises(UnsupportedPlatform):
        runtime.run_native(boom)


def test_run_osascript_refuses(linux):
    with pytest.raises(UnsupportedPlatform):
        _REAL_RUN_OSASCRIPT('return "x"')


def test_tracked_run_refuses(linux):
    with pytest.raises(UnsupportedPlatform):
        _REAL_TRACKED_RUN(["true"], timeout=5.0)


def test_mac_region_refuses(linux):
    with pytest.raises(UnsupportedPlatform):
        runtime.mac_region()


def test_diagnose_refuses(linux, monkeypatch):
    monkeypatch.setattr(doctor, "_EK_ENTITIES", ())  # what a Linux import leaves
    with pytest.raises(UnsupportedPlatform):
        doctor.diagnose()


def test_bootstrap_returns_without_a_native_call(linux, monkeypatch):
    calls = []
    monkeypatch.setattr(eventkit, "run_native", lambda fn: calls.append(fn))
    assert eventkit.bootstrap() is None
    assert calls == []


def test_guard_answers_with_the_platform_reason(linux):
    called = []
    with pytest.raises(ToolError, match="runs only on macOS"):
        server._guard(lambda: called.append(1))()
    assert called == []


def test_ping_and_now_still_answer(linux):
    assert server.ping() == "macos-apps-mcp ok"
    assert "timezone" in server.now()
