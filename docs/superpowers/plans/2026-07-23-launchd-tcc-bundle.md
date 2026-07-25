# launchd Daemon + TCC-to-Bundle (.app) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One launchd-run, Developer-ID-signed `.app` holds every TCC grant; clients connect through a tiny stdio shim over a unix socket (#71).

**Architecture:** New deployment plane in three modules — `daemon.py` (owned-socket UDS serving + single-instance + shim proxy), `deploy.py` (SMAppService register/unregister + TCC identity report), `cli.py` (role dispatch; bare invocation stays stdio). Packaging is a hand-rolled bundle script (spike-proven shape): python-build-standalone interpreter as `Contents/MacOS/macos-apps-mcp`, stdlib at `Contents/lib/python3.14/` (getpath finds it env-free), vendored site-packages, inside-out signing.

**Tech Stack:** Python 3.14, FastMCP 3.4 (`http_app`, `create_proxy`), uvicorn (fd-based UDS), httpx (UDS transport), pyobjc ServiceManagement, codesign/notarytool, pytest, ruff.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-23-mac-mcp-71-launchd-tcc-bundle-design.md` (design v2 + fork resolutions). Transport = streamable-http over UDS; shim = `fastmcp.server.create_proxy` (NOT deprecated `FastMCP.as_proxy`); packaging = hand-rolled.
- **`macos-apps-mcp` with no args MUST behave exactly as today** (stdio, bootstrap, lifecycle guards). stdio/venv mode is first-class; daemon mode is additive.
- Socket: `state_dir()/daemon` dir `0700`, socket file `chmod 0600` after our own bind (uvicorn gets the **fd**, never the path — it would create `0666`). Env override `MACOS_APPS_MCP_SOCKET` for tests.
- Shim fails FAST on absent/refused socket: one stderr line naming `macos-apps-mcp install-agent`, exit code 2, never a hang.
- Bundle id `ren.lav.macos-apps-mcp` (permanent). Team `VUMUR696L9`. Signing: inside-out per-Mach-O, `--timestamp --options runtime`, **never `codesign --deep`**. Library validation ON (no `disable-library-validation` unless the hardened-runtime import test forces it). Entitlement: `com.apple.security.automation.apple-events`.
- New direct deps get pinned in `pyproject.toml` with a why-comment (repo convention): `uvicorn`, `httpx`, `pyobjc-framework-ServiceManagement`.
- SMAppService registers plists from the **calling bundle** → `register`/`unregister` argv roles run in-bundle; the pip-side `install-agent` invokes the bundle binary. Consent prompts fire **inside the daemon** (via a doctor call over the UDS), never from the terminal.
- Line-length 88; ruff `E,F,I,UP,B,SIM`; `ruff format`. Verify before done: `uv run pytest && uv run ruff check . && uv run ruff format --check .`. Integration (`-m integration`) on-device only, never CI.

---

### Task 1: `daemon.py` — socket path + owned single-instance bind

**Files:**
- Create: `macos_apps_mcp/daemon.py`
- Modify: `pyproject.toml` (add `uvicorn`, `httpx` deps — used by Tasks 2–3; one dep edit, one `uv lock`)
- Test: `tests/test_daemon.py`

**Interfaces:**
- Produces: `socket_path() -> Path` (env `MACOS_APPS_MCP_SOCKET` override, else `state_dir()/daemon/mcp.sock`; parent dir created `0700`), `AlreadyRunning(Exception)`, `bind_socket(path: Path) -> socket.socket` (bound+listening AF_UNIX socket, file `0600`; live owner → `AlreadyRunning`; stale file → unlink + rebind).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_daemon.py
import socket
import stat

import pytest

from macos_apps_mcp import daemon


def test_socket_path_env_override(tmp_path, monkeypatch):
    p = tmp_path / "s.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    assert daemon.socket_path() == p


def test_bind_socket_perms(tmp_path):
    p = tmp_path / "d" / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    finally:
        s.close()


def test_bind_socket_live_owner_raises(tmp_path):
    p = tmp_path / "mcp.sock"
    s1 = daemon.bind_socket(p)
    try:
        with pytest.raises(daemon.AlreadyRunning):
            daemon.bind_socket(p)
    finally:
        s1.close()


def test_bind_socket_stale_file_rebinds(tmp_path):
    p = tmp_path / "mcp.sock"
    daemon.bind_socket(p).close()  # closed listener leaves a stale file
    assert p.exists()
    s = daemon.bind_socket(p)  # ECONNREFUSED probe → unlink → rebind
    try:
        c = socket.socket(socket.AF_UNIX)
        c.connect(str(p))  # proves it is live again
        c.close()
    finally:
        s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: FAIL — `ModuleNotFoundError: macos_apps_mcp.daemon`.

- [ ] **Step 3: Write minimal implementation**

```python
# macos_apps_mcp/daemon.py
"""Deployment plane (#71): the launchd daemon serves the existing FastMCP server over a
unix domain socket (streamable-http), and the shim bridges a client's stdio to it via
a FastMCP proxy. The daemon OWNS the socket bind (perms + single-instance); uvicorn is
handed the fd, never the path (uvicorn's own bind would create the socket 0666)."""

from __future__ import annotations

import errno
import os
import socket
from pathlib import Path

from .audit import state_dir


class AlreadyRunning(Exception):
    """A live daemon already owns the socket."""


def socket_path() -> Path:
    override = os.environ.get("MACOS_APPS_MCP_SOCKET")
    if override:
        return Path(override)
    d = state_dir() / "daemon"
    d.mkdir(mode=0o700, exist_ok=True)
    return d / "mcp.sock"


def bind_socket(path: Path) -> socket.socket:
    """Bind+listen the daemon socket with single-instance semantics (spec §D):
    EADDRINUSE → connect-probe; live owner → AlreadyRunning; refused → stale file
    from a crash → unlink + rebind. File 0600, parent 0700."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(str(path))
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            s.close()
            raise
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)  # stale — crashed owner never unlinked
            s.bind(str(path))
        else:
            s.close()
            raise AlreadyRunning(f"a daemon already owns {path}") from e
        finally:
            probe.close()
    os.chmod(path, 0o600)
    s.listen()
    return s
```

Add to `pyproject.toml` `dependencies` (then `uv lock`):

```toml
    "uvicorn>=0.30",                      # imported directly (daemon.py: fd-based UDS serving)
    "httpx>=0.27",                        # imported directly (daemon.py: shim's UDS transport)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/daemon.py tests/test_daemon.py pyproject.toml uv.lock
git commit -m "feat(daemon): owned UDS bind — perms + single-instance (#71)"
```

---

### Task 2: `daemon.serve()` — uvicorn on the owned fd

**Files:**
- Modify: `macos_apps_mcp/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `server.mcp` (the FastMCP instance), Task 1's `bind_socket`.
- Produces: `serve() -> None` (blocking; binds via `bind_socket(socket_path())`, runs `uvicorn.Server(Config(mcp.http_app(), fd=s.fileno(), log_level="warning"))`, unlinks the socket on exit), and test helper `_uds_client_factory(path)` (an httpx factory usable by tests and the Task 3 shim).

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import threading

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


def test_serve_two_concurrent_sessions(tmp_path, monkeypatch):
    p = tmp_path / "mcp.sock"
    monkeypatch.setenv("MACOS_APPS_MCP_SOCKET", str(p))
    t = threading.Thread(target=daemon.serve, daemon=True)
    t.start()
    for _ in range(100):  # wait for the socket
        if p.exists():
            break
        __import__("time").sleep(0.05)

    async def go():
        def transport():
            return StreamableHttpTransport(
                "http://daemon/mcp",
                httpx_client_factory=daemon._uds_client_factory(p),
            )

        async with Client(transport()) as c1, Client(transport()) as c2:
            r1, r2 = await asyncio.gather(c1.call_tool("ping"), c2.call_tool("ping"))
            assert "ok" in r1.content[0].text and "ok" in r2.content[0].text

    asyncio.run(go())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_daemon.py::test_serve_two_concurrent_sessions -v`
Expected: FAIL — `AttributeError: serve`.

- [ ] **Step 3: Write minimal implementation**

```python
import httpx
import uvicorn


def _uds_client_factory(path: Path):
    """httpx AsyncClient factory routing all requests over the unix socket. The URL
    host is a dummy — never resolved."""

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(path)), **kwargs
        )

    return factory


def serve() -> None:
    """Run the FastMCP server as the daemon: streamable-http over the owned UDS.
    One MCP session per client connection (fork resolution, spec)."""
    from .server import mcp  # late: importing server pulls the adapter tree

    path = socket_path()
    s = bind_socket(path)
    try:
        config = uvicorn.Config(mcp.http_app(), fd=s.fileno(), log_level="warning")
        uvicorn.Server(config).run()
    finally:
        s.close()
        path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: PASS (5 tests). The `ping` tool already exists in `server.py` and touches no TCC.

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/daemon.py tests/test_daemon.py
git commit -m "feat(daemon): serve FastMCP streamable-http over the owned UDS (#71)"
```

---

### Task 3: shim — fail-fast + FastMCP proxy on stdio

**Files:**
- Modify: `macos_apps_mcp/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `_uds_client_factory`, `socket_path`; `fastmcp.server.create_proxy`, `fastmcp.Client`.
- Produces: `shim_check(path: Path) -> None` (raises `SystemExit(2)` with the actionable message when the socket is absent or connect-refused), `run_shim() -> None` (check, then `create_proxy(...)` served on stdio).

- [ ] **Step 1: Write the failing tests**

```python
def test_shim_check_absent_socket_exits_2(tmp_path):
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(tmp_path / "missing.sock")
    assert e.value.code == 2


def test_shim_check_stale_socket_exits_2(tmp_path):
    p = tmp_path / "mcp.sock"
    daemon.bind_socket(p).close()  # stale file, nobody listening
    with pytest.raises(SystemExit) as e:
        daemon.shim_check(p)
    assert e.value.code == 2


def test_shim_check_live_socket_passes(tmp_path):
    p = tmp_path / "mcp.sock"
    s = daemon.bind_socket(p)
    try:
        daemon.shim_check(p)  # no raise
    finally:
        s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_daemon.py -k shim_check -v`
Expected: FAIL — `AttributeError: shim_check`.

- [ ] **Step 3: Write minimal implementation**

```python
import sys

from fastmcp import Client as _Client
from fastmcp.client.transports import StreamableHttpTransport as _HttpTransport
from fastmcp.server import create_proxy


def shim_check(path: Path) -> None:
    """Fail FAST when no daemon is serving — a hanging shim looks like a wedged
    client (spec §C). One actionable stderr line, exit 2."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.connect(str(path))
    except OSError:
        print(
            f"macos-apps-mcp: daemon not running (no socket at {path}) — "
            "run `macos-apps-mcp install-agent`",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    finally:
        probe.close()


def run_shim() -> None:
    """Bridge the client's stdio to the daemon over the UDS (FastMCP proxy — the
    fork-resolved ~15-line shim). No TCC surface: this process only moves bytes."""
    path = socket_path()
    shim_check(path)
    proxy = create_proxy(
        _Client(
            _HttpTransport(
                "http://daemon/mcp", httpx_client_factory=_uds_client_factory(path)
            )
        )
    )
    proxy.run()  # stdio transport
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_daemon.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/daemon.py tests/test_daemon.py
git commit -m "feat(daemon): stdio shim via fastmcp create_proxy, fail-fast (#71)"
```

---

### Task 4: `cli.py` — role dispatch, bare invocation unchanged

**Files:**
- Create: `macos_apps_mcp/cli.py`
- Modify: `macos_apps_mcp/__init__.py` (export `main` from `cli`), `macos_apps_mcp/server.py` (docstring of `main` only — it becomes the stdio role, called by cli)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `server.main` (stdio), `daemon.serve`, `daemon.run_shim`; Task 6's `deploy.register_agent`/`deploy.unregister_agent` and Task 8's `deploy.install_agent`/`deploy.uninstall_agent` are dispatched by name — cli imports `deploy` lazily inside those branches so this task ships before deploy exists.
- Produces: `cli.main() -> None` — argv role: *(none)* → `server.main()` **unchanged** (bootstrap + lifecycle guards + stdio); `daemon` → `daemon.serve()` (no lifecycle guards — launchd `KeepAlive` owns restart; ppid is launchd); `shim` → `daemon.run_shim()`; `register`/`unregister` → in-bundle SMAppService calls (Task 6); `install-agent`/`uninstall-agent` → pip-side orchestration (Task 8).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import pytest

from macos_apps_mcp import cli


def test_bare_invocation_is_stdio(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.server.main", lambda: called.append("stdio"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp"])
    cli.main()
    assert called == ["stdio"]


def test_daemon_role(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.daemon.serve", lambda: called.append("daemon"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "daemon"])
    cli.main()
    assert called == ["daemon"]


def test_shim_role(monkeypatch):
    called = []
    monkeypatch.setattr("macos_apps_mcp.daemon.run_shim", lambda: called.append("shim"))
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "shim"])
    cli.main()
    assert called == ["shim"]


def test_unknown_role_exits_nonzero(monkeypatch):
    monkeypatch.setattr("sys.argv", ["macos-apps-mcp", "bogus"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: macos_apps_mcp.cli`.

- [ ] **Step 3: Write minimal implementation**

```python
# macos_apps_mcp/cli.py
"""Role dispatch (#71). Bare invocation stays the stdio server byte-for-byte — every
existing client config keeps working. Roles are positional argv (no flags): the bundle
executable and the venv entry point share this dispatch."""

from __future__ import annotations

import sys

_ROLES = ("daemon", "shim", "register", "unregister", "install-agent", "uninstall-agent")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        from . import server

        server.main()  # stdio — bootstrap + lifecycle guards, unchanged
        return
    role = args[0]
    if role == "daemon":
        from . import daemon

        daemon.serve()  # no lifecycle guards: launchd KeepAlive owns restart
    elif role == "shim":
        from . import daemon

        daemon.run_shim()
    elif role in ("register", "unregister"):
        from . import deploy

        (deploy.register_agent if role == "register" else deploy.unregister_agent)()
    elif role == "install-agent":
        from . import deploy

        deploy.install_agent(args[1:])
    elif role == "uninstall-agent":
        from . import deploy

        deploy.uninstall_agent()
    else:
        print(f"unknown role {role!r}; one of: {', '.join(_ROLES)}", file=sys.stderr)
        raise SystemExit(2)
```

`macos_apps_mcp/__init__.py`: change `from .server import main, mcp` → `from .cli import main` + `from .server import mcp` (keep both exports).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py tests/test_daemon.py -v && uv run pytest -q`
Expected: PASS, full suite green (no existing test regresses — bare invocation path unchanged).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/cli.py macos_apps_mcp/__init__.py tests/test_cli.py
git commit -m "feat(cli): role dispatch — stdio default, daemon/shim/agent roles (#71)"
```

---

### Task 5: packaging templates + hand-rolled bundle build script

**Files:**
- Create: `packaging/Info.plist`, `packaging/entitlements.plist`, `packaging/ren.lav.macos-apps-mcp.plist` (LaunchAgent, ships in-bundle), `scripts/build_app.sh`
- Test: `tests/test_packaging.py` (template lint only — the build itself is Task 9 on-device)

**Interfaces:**
- Produces: `scripts/build_app.sh [--sign "IDENTITY"] [--notarize PROFILE] [--out DIR]` → `DIR/macos-apps-mcp.app`. Layout (spec §A + getpath): `Contents/MacOS/macos-apps-mcp` = the python-build-standalone interpreter binary (real file); stdlib at `Contents/lib/python3.14/`; our package + deps `pip install --target Contents/lib/python3.14/site-packages`; `Contents/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist`; `Contents/Info.plist`. Signing: inside-out (every `.so`/`.dylib`, then the main binary, then the bundle) with `--timestamp --options runtime`; unsigned build when `--sign` omitted (dev). `--notarize` runs `notarytool submit --wait` + `stapler staple`.

- [ ] **Step 1: Write the failing lint test**

```python
# tests/test_packaging.py
import plistlib
import subprocess
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "packaging"


def test_info_plist_contract():
    info = plistlib.loads((PKG / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "ren.lav.macos-apps-mcp"
    assert info["CFBundleExecutable"] == "macos-apps-mcp"
    assert info["LSUIElement"] is True
    for key in (
        "NSCalendarsFullAccessUsageDescription",
        "NSRemindersFullAccessUsageDescription",
        "NSContactsUsageDescription",
        "NSAppleEventsUsageDescription",
    ):
        assert info[key]


def test_entitlements_minimal():
    ents = plistlib.loads((PKG / "entitlements.plist").read_bytes())
    assert ents == {"com.apple.security.automation.apple-events": True}


def test_launchagent_plist_contract():
    la = plistlib.loads((PKG / "ren.lav.macos-apps-mcp.plist").read_bytes())
    assert la["Label"] == "ren.lav.macos-apps-mcp"
    assert la["ProgramArguments"][1:] == ["-m", "macos_apps_mcp", "daemon"]
    assert la["KeepAlive"] is True and la["ThrottleInterval"] >= 5


def test_build_script_never_deep_signs():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "build_app.sh").read_text()
    assert "--deep" not in src
    assert "--timestamp" in src and "runtime" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: FAIL — files missing.

- [ ] **Step 3: Write the templates + script**

`packaging/Info.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>ren.lav.macos-apps-mcp</string>
  <key>CFBundleExecutable</key><string>macos-apps-mcp</string>
  <key>CFBundleName</key><string>macos-apps-mcp</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleShortVersionString</key><string>0.8.0</string>
  <key>LSUIElement</key><true/>
  <key>NSCalendarsFullAccessUsageDescription</key>
  <string>macos-apps-mcp reads and writes your calendar on request from your MCP client.</string>
  <key>NSRemindersFullAccessUsageDescription</key>
  <string>macos-apps-mcp reads and writes your reminders on request from your MCP client.</string>
  <key>NSContactsUsageDescription</key>
  <string>macos-apps-mcp searches your contacts on request from your MCP client.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>macos-apps-mcp automates Mail, Notes and other apps on request from your MCP client.</string>
</dict></plist>
```

`packaging/entitlements.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.automation.apple-events</key><true/>
</dict></plist>
```

`packaging/ren.lav.macos-apps-mcp.plist` (`__APP__` is substituted by the build script with the install path):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ren.lav.macos-apps-mcp</string>
  <key>ProgramArguments</key><array>
    <string>__APP__/Contents/MacOS/macos-apps-mcp</string>
    <string>-m</string><string>macos_apps_mcp</string><string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
</dict></plist>
```

`scripts/build_app.sh` (complete):

```bash
#!/bin/bash
# Build macos-apps-mcp.app — hand-rolled (spec fork resolution). Layout puts the
# python-build-standalone interpreter at Contents/MacOS/<exe> and the stdlib at
# Contents/lib/python3.14 so CPython's getpath finds prefix relative to the
# executable — NO PYTHONHOME/PYTHONPATH env needed by launchd or client configs.
# Signing is INSIDE-OUT per Mach-O with --timestamp --options runtime; never --deep.
set -euo pipefail

SIGN="" NOTARIZE="" OUT="dist"
while [[ $# -gt 0 ]]; do case "$1" in
  --sign) SIGN="$2"; shift 2;;
  --notarize) NOTARIZE="$2"; shift 2;;
  --out) OUT="$2"; shift 2;;
  *) echo "unknown arg $1" >&2; exit 2;;
esac; done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYVER=3.14
STD="$(ls -d "$HOME"/.local/share/uv/python/cpython-${PYVER}*-macos-*/ | sort | tail -1)"
APP="$OUT/macos-apps-mcp.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/lib" \
  "$APP/Contents/Library/LaunchAgents" "$APP/Contents/Resources"

cp "$STD/bin/python${PYVER}" "$APP/Contents/MacOS/macos-apps-mcp"   # real file (codesign)
cp -R "$STD/lib/python${PYVER}" "$APP/Contents/lib/python${PYVER}"  # stdlib for getpath
SITE="$APP/Contents/lib/python${PYVER}/site-packages"
uv pip install --python "$STD/bin/python${PYVER}" --target "$SITE" "$REPO"
sed "s|__APP__|/Applications/macos-apps-mcp.app|" \
  "$REPO/packaging/ren.lav.macos-apps-mcp.plist" \
  > "$APP/Contents/Library/LaunchAgents/ren.lav.macos-apps-mcp.plist"
cp "$REPO/packaging/Info.plist" "$APP/Contents/Info.plist"

# Smoke: env-free import through the bundled interpreter (getpath layout claim).
env -i "$APP/Contents/MacOS/macos-apps-mcp" -c "import macos_apps_mcp" \
  || { echo "BUNDLE SMOKE FAILED: getpath layout wrong"; exit 1; }

if [[ -n "$SIGN" ]]; then
  ENTS="$REPO/packaging/entitlements.plist"
  # inside-out: every nested Mach-O first, then the main binary, then the bundle
  find "$APP/Contents/lib" \( -name '*.so' -o -name '*.dylib' \) -print0 |
    while IFS= read -r -d '' f; do
      codesign --force --timestamp --options runtime -s "$SIGN" "$f"
    done
  codesign --force --timestamp --options runtime --entitlements "$ENTS" \
    -s "$SIGN" "$APP/Contents/MacOS/macos-apps-mcp"
  codesign --force --timestamp --options runtime --entitlements "$ENTS" \
    -s "$SIGN" "$APP"
  codesign --verify --strict --verbose=2 "$APP"
fi

if [[ -n "$NOTARIZE" ]]; then
  ditto -c -k --keepParent "$APP" "$OUT/macos-apps-mcp.zip"
  xcrun notarytool submit "$OUT/macos-apps-mcp.zip" \
    --keychain-profile "$NOTARIZE" --wait
  xcrun stapler staple "$APP"
fi
echo "built: $APP"
```

`chmod +x scripts/build_app.sh`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_packaging.py -v`
Expected: PASS (4 tests). Do NOT run the build script here — Task 9 runs it on-device.

- [ ] **Step 5: Commit**

```bash
git add packaging/ scripts/build_app.sh tests/test_packaging.py
git commit -m "feat(packaging): bundle templates + inside-out build script (#71)"
```

---

### Task 6: `deploy.py` — SMAppService register/unregister + TCC identity report

**Files:**
- Create: `macos_apps_mcp/deploy.py`
- Modify: `pyproject.toml` (add `pyobjc-framework-ServiceManagement`)
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces:
  - `register_agent() -> None` / `unregister_agent() -> None` — in-bundle roles (SMAppService registers plists from the **calling bundle**): `SMAppService.agentServiceWithPlistName_("ren.lav.macos-apps-mcp.plist")` → `registerAndReturnError_(None)` / `unregisterAndReturnError_(None)`; raise `NativeError` with the SM error description on failure. When not running from a bundle (`NSBundle.mainBundle` has no id) → `NativeError` naming the build script.
  - `agent_status() -> str` — maps `SMAppService.status()` int → `"not-registered" | "enabled" | "requires-approval" | "not-found"`.
  - `grant_identities(services: list[str] | None = None) -> dict[str, list[dict]] | None` — reads `~/Library/Application Support/com.apple.TCC/TCC.db` (`SELECT service, client, auth_value FROM access`), returns `{service: [{"client": …, "granted": bool}]}` for the doctor; `None` when unreadable (pre-FDA chicken-and-egg, spec §E) — never raises, never mis-parses (wrap all sqlite errors).
- Default service list: `kTCCServiceCalendar`, `kTCCServiceReminders`, `kTCCServiceAddressBook`, `kTCCServiceAppleEvents`, `kTCCServiceSystemPolicyAllFiles`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_deploy.py
import sqlite3

from macos_apps_mcp import deploy


def _fake_tcc(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE access (service TEXT, client TEXT, auth_value INT)")
    c.executemany(
        "INSERT INTO access VALUES (?,?,?)",
        [
            ("kTCCServiceCalendar", "com.apple.Terminal", 2),
            ("kTCCServiceCalendar", "ren.lav.macos-apps-mcp", 2),
            ("kTCCServiceSystemPolicyAllFiles", "ren.lav.macos-apps-mcp", 0),
        ],
    )
    c.commit()
    c.close()


def test_grant_identities_maps_rows(tmp_path, monkeypatch):
    db = tmp_path / "TCC.db"
    _fake_tcc(db)
    monkeypatch.setattr(deploy, "_TCC_DB", db)
    out = deploy.grant_identities(["kTCCServiceCalendar", "kTCCServiceSystemPolicyAllFiles"])
    cal = out["kTCCServiceCalendar"]
    assert {"client": "ren.lav.macos-apps-mcp", "granted": True} in cal
    assert {"client": "com.apple.Terminal", "granted": True} in cal
    assert out["kTCCServiceSystemPolicyAllFiles"] == [
        {"client": "ren.lav.macos-apps-mcp", "granted": False}
    ]


def test_grant_identities_unreadable_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_TCC_DB", tmp_path / "absent" / "TCC.db")
    assert deploy.grant_identities() is None


def test_agent_status_maps_ints(monkeypatch):
    class FakeSvc:
        def status(self):
            return 1

    monkeypatch.setattr(deploy, "_agent_service", lambda: FakeSvc())
    assert deploy.agent_status() == "enabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deploy.py -v`
Expected: FAIL — `ModuleNotFoundError: macos_apps_mcp.deploy`.

- [ ] **Step 3: Write minimal implementation**

```python
# macos_apps_mcp/deploy.py
"""Agent lifecycle + grant-identity reporting (#71). SMAppService registers plists
from the CALLING bundle — so register/unregister run as argv roles of the bundle
executable; the pip-side install-agent invokes them (never SMAppService directly)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .errors import NativeError

_PLIST = "ren.lav.macos-apps-mcp.plist"
_TCC_DB = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
_SERVICES = [
    "kTCCServiceCalendar",
    "kTCCServiceReminders",
    "kTCCServiceAddressBook",
    "kTCCServiceAppleEvents",
    "kTCCServiceSystemPolicyAllFiles",
]
# SMAppService.status() ints (ServiceManagement.h)
_STATUS = {0: "not-registered", 1: "enabled", 2: "requires-approval", 3: "not-found"}


def _agent_service():
    import Foundation
    from ServiceManagement import SMAppService

    if Foundation.NSBundle.mainBundle().bundleIdentifier() is None:
        raise NativeError(
            "not running from the .app bundle — SMAppService registers plists from "
            "the calling bundle. Build with scripts/build_app.sh and invoke the "
            "bundle executable. Do not retry from the venv."
        )
    return SMAppService.agentServiceWithPlistName_(_PLIST)


def register_agent() -> None:
    ok, err = _agent_service().registerAndReturnError_(None)
    if not ok:
        raise NativeError(f"SMAppService register failed: {err}")


def unregister_agent() -> None:
    ok, err = _agent_service().unregisterAndReturnError_(None)
    if not ok:
        raise NativeError(f"SMAppService unregister failed: {err}")


def agent_status() -> str:
    return _STATUS.get(int(_agent_service().status()), "unknown")


def grant_identities(services: list[str] | None = None) -> dict | None:
    """Which identity holds each TCC grant — None when TCC.db is unreadable
    (reading it needs FDA for OUR responsible process: the spec §E chicken-and-egg).
    Never raises; a wrong claim is worse than no claim."""
    wanted = services or _SERVICES
    try:
        conn = sqlite3.connect(f"file:{_TCC_DB}?mode=ro", uri=True)
        try:
            marks = ",".join("?" for _ in wanted)
            rows = conn.execute(
                f"SELECT service, client, auth_value FROM access "  # noqa: S608
                f"WHERE service IN ({marks})",
                wanted,
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    out: dict[str, list[dict]] = {}
    for service, client, auth in rows:
        out.setdefault(service, []).append(
            {"client": client, "granted": auth == 2}
        )
    return out
```

Add to `pyproject.toml` dependencies (then `uv lock`):

```toml
    "pyobjc-framework-ServiceManagement>=10.0",  # SMAppService agent registration (deploy.py)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deploy.py tests/test_cli.py -v`
Expected: PASS (deploy tests + the cli register/unregister dispatch now resolves).

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/deploy.py tests/test_deploy.py pyproject.toml uv.lock
git commit -m "feat(deploy): SMAppService agent lifecycle + TCC identity report (#71)"
```

---

### Task 7: doctor — mode + grant-identity section

**Files:**
- Modify: `macos_apps_mcp/doctor.py`, `macos_apps_mcp/daemon.py` (daemon sets `MACOS_APPS_MCP_ROLE=daemon` in `serve()` before importing server)
- Test: `tests/test_doctor_deploy.py`

**Interfaces:**
- Consumes: `deploy.grant_identities`, `deploy.agent_status`.
- Produces: `diagnose()` output gains `"deployment"`: `{"mode": "daemon"|"stdio", "agent": <status or "unavailable: …">, "grant_identities": <dict or None>, "note": <one-line explanation when grant_identities is None>}`. Mode = `os.environ.get("MACOS_APPS_MCP_ROLE") == "daemon"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_deploy.py
from macos_apps_mcp import doctor


def test_deployment_section_stdio_graceful(monkeypatch):
    monkeypatch.delenv("MACOS_APPS_MCP_ROLE", raising=False)
    monkeypatch.setattr("macos_apps_mcp.deploy.grant_identities", lambda: None)
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.agent_status",
        lambda: (_ for _ in ()).throw(Exception("no bundle")),
    )
    d = doctor.diagnose()["deployment"]
    assert d["mode"] == "stdio"
    assert d["grant_identities"] is None
    assert "FDA" in d["note"]
    assert d["agent"].startswith("unavailable")


def test_deployment_section_daemon_mode(monkeypatch):
    monkeypatch.setenv("MACOS_APPS_MCP_ROLE", "daemon")
    monkeypatch.setattr(
        "macos_apps_mcp.deploy.grant_identities",
        lambda: {"kTCCServiceCalendar": [{"client": "ren.lav.macos-apps-mcp", "granted": True}]},
    )
    monkeypatch.setattr("macos_apps_mcp.deploy.agent_status", lambda: "enabled")
    d = doctor.diagnose()["deployment"]
    assert d["mode"] == "daemon" and d["agent"] == "enabled"
    assert d["grant_identities"]["kTCCServiceCalendar"][0]["granted"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_doctor_deploy.py -v`
Expected: FAIL — `KeyError: 'deployment'`.

- [ ] **Step 3: Implement**

In `doctor.py` (inside `diagnose`, adding one section; match its existing dict style):

```python
    from . import deploy

    ids = deploy.grant_identities()
    try:
        agent = deploy.agent_status()
    except Exception as e:  # not in a bundle / SM bridge absent — report, don't die
        agent = f"unavailable: {e}"
    report["deployment"] = {
        "mode": "daemon" if os.environ.get("MACOS_APPS_MCP_ROLE") == "daemon" else "stdio",
        "agent": agent,
        "grant_identities": ids,
        "note": (
            "TCC.db unreadable — grant identity report needs Full Disk Access for "
            "THIS process's responsible identity (grant it, or run via the daemon)."
            if ids is None
            else "grants listed per identity; the daemon identity is "
            "ren.lav.macos-apps-mcp"
        ),
    }
```

In `daemon.serve()`, before the server import: `os.environ["MACOS_APPS_MCP_ROLE"] = "daemon"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_doctor_deploy.py -v && uv run pytest -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/doctor.py macos_apps_mcp/daemon.py tests/test_doctor_deploy.py
git commit -m "feat(doctor): deployment section — mode, agent status, grant identities (#71)"
```

---

### Task 8: `install-agent` / `uninstall-agent` orchestration

**Files:**
- Modify: `macos_apps_mcp/deploy.py`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Consumes: Task 6 primitives; `daemon.socket_path`; the daemon's `doctor` MCP tool (prompts must fire in the DAEMON process so they attach to the bundle identity).
- Produces: `install_agent(argv: list[str]) -> None` (steps: resolve app path — default `/Applications/macos-apps-mcp.app`, `--app PATH` override; translocation guard — if `com.apple.quarantine` xattr present, `spctl -a` must pass, then strip the xattr; invoke `<app>/Contents/MacOS/macos-apps-mcp -m macos_apps_mcp register`; wait for the socket; call `doctor(request=True)` over the UDS as an MCP client; print the FDA deep-link + per-client config snippet). `uninstall_agent() -> None` (invoke the bundle's `unregister`, remove socket dir, print the `tccutil reset All ren.lav.macos-apps-mcp` line).

- [ ] **Step 1: Write the failing tests**

```python
def test_install_agent_missing_app_fails_actionably(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit) as e:
        deploy.install_agent(["--app", str(tmp_path / "nope.app")])
    assert e.value.code == 2
    assert "build_app.sh" in capsys.readouterr().err


def test_install_agent_orchestrates(tmp_path, monkeypatch, capsys):
    app = tmp_path / "macos-apps-mcp.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    exe = app / "Contents/MacOS/macos-apps-mcp"
    exe.write_text("")
    exe.chmod(0o755)
    calls = []
    monkeypatch.setattr(deploy, "_run_bundle_role", lambda a, role: calls.append(role))
    monkeypatch.setattr(deploy, "_wait_for_socket", lambda timeout=30: calls.append("socket"))
    monkeypatch.setattr(deploy, "_request_grants_via_daemon", lambda: calls.append("prompts"))
    deploy.install_agent(["--app", str(app)])
    assert calls == ["register", "socket", "prompts"]
    out = capsys.readouterr().out
    assert "Privacy_AllFiles" in out  # FDA deep-link printed
    assert '"shim"' in out  # client config snippet
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_deploy.py -k install_agent -v`
Expected: FAIL — `AttributeError: install_agent`.

- [ ] **Step 3: Implement**

```python
import json
import subprocess
import sys
import time


def _run_bundle_role(app: Path, role: str) -> None:
    exe = app / "Contents/MacOS/macos-apps-mcp"
    subprocess.run([str(exe), "-m", "macos_apps_mcp", role], check=True, timeout=60)


def _wait_for_socket(timeout: float = 30) -> None:
    from .daemon import socket_path

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if socket_path().exists():
            return
        time.sleep(0.25)
    raise NativeError("daemon socket never appeared — check `launchctl print` / logs")


def _request_grants_via_daemon() -> None:
    """Fire every consent prompt FROM the daemon process (bundle identity — prompts
    from this terminal would attach to the terminal instead). doctor(request=True)
    is the existing proactive-prompt pass."""
    import asyncio

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    from .daemon import _uds_client_factory, socket_path

    async def go():
        transport = StreamableHttpTransport(
            "http://daemon/mcp", httpx_client_factory=_uds_client_factory(socket_path())
        )
        async with Client(transport) as c:
            await c.call_tool("doctor", {"request": True})

    asyncio.run(go())


def _quarantine_guard(app: Path) -> None:
    q = subprocess.run(
        ["xattr", "-p", "com.apple.quarantine", str(app)], capture_output=True
    )
    if q.returncode == 0:  # quarantined download — verify, then strip (translocation)
        subprocess.run(["spctl", "-a", str(app)], check=True)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(app)], check=True)


def install_agent(argv: list[str]) -> None:
    app = Path("/Applications/macos-apps-mcp.app")
    if argv[:1] == ["--app"]:
        app = Path(argv[1])
    if not (app / "Contents/MacOS/macos-apps-mcp").exists():
        print(
            f"no bundle at {app} — build one with scripts/build_app.sh "
            "(then copy to /Applications)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    _quarantine_guard(app)
    _run_bundle_role(app, "register")
    _wait_for_socket()
    _request_grants_via_daemon()
    exe = app / "Contents/MacOS/macos-apps-mcp"
    snippet = {"command": str(exe), "args": ["-m", "macos_apps_mcp", "shim"]}
    print(
        "Full Disk Access must be granted by hand — opening the pane:\n"
        "  open 'x-apple.systempreferences:com.apple.preference.security"
        "?Privacy_AllFiles'\n"
        f"Point each MCP client at the shim:\n{json.dumps(snippet, indent=2)}"
    )


def uninstall_agent() -> None:
    from .daemon import socket_path

    app = Path("/Applications/macos-apps-mcp.app")
    if (app / "Contents/MacOS/macos-apps-mcp").exists():
        _run_bundle_role(app, "unregister")
    socket_path().unlink(missing_ok=True)
    print("agent unregistered. To wipe grants: tccutil reset All ren.lav.macos-apps-mcp")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_deploy.py -v && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add macos_apps_mcp/deploy.py tests/test_deploy.py
git commit -m "feat(deploy): install-agent/uninstall-agent orchestration (#71)"
```

---

### Task 9: on-device integration + docs

**Files:**
- Create: `tests/test_daemon_integration.py`, `docs/DAEMON.md`
- Test: itself (`-m integration`, manual on this Mac — NEVER CI)

- [ ] **Step 1: Write the integration tests**

```python
# tests/test_daemon_integration.py
"""On-device gate for #71 (run manually: uv run pytest -m integration -k daemon).
The full acceptance (grants shared across Terminal/Claude Desktop/VS Code after ONE
grant to the daemon identity) needs human grant clicks — the manual checklist lives
in docs/DAEMON.md; these tests cover what automation can reach."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_app.sh"


def test_build_unsigned_bundle_and_smoke(tmp_path):
    subprocess.run([str(BUILD), "--out", str(tmp_path)], check=True, timeout=600)
    exe = tmp_path / "macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp"
    out = subprocess.run(  # env-free: proves the getpath layout, no PYTHONHOME
        ["env", "-i", str(exe), "-c", "import macos_apps_mcp; print('ok')"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.stdout.strip() == "ok", out.stderr


def test_daemon_shim_end_to_end(tmp_path, monkeypatch):
    """venv daemon + venv shim over a private socket: real subprocesses, real UDS."""
    import os

    sock = tmp_path / "mcp.sock"
    env = {  # HOME is required: adapters compute Path.home() constants at import
        "MACOS_APPS_MCP_SOCKET": str(sock),
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ["HOME"],
    }
    d = subprocess.Popen(
        [sys.executable, "-m", "macos_apps_mcp", "daemon"], env=env
    )
    try:
        for _ in range(100):
            if sock.exists():
                break
            __import__("time").sleep(0.1)
        assert sock.exists(), "daemon never bound its socket"
        probe = subprocess.run(  # live daemon → shim connects, EOF → clean exit
            [sys.executable, "-m", "macos_apps_mcp", "shim"],
            env=env,
            input=b"",  # immediate EOF: must exit 0 promptly, never hang
            timeout=30,
        )
        assert probe.returncode == 0
    finally:
        d.terminate()
        d.wait(timeout=10)


def test_shim_fail_fast_no_daemon(tmp_path):
    import os

    out = subprocess.run(
        [sys.executable, "-m", "macos_apps_mcp", "shim"],
        env={
            "MACOS_APPS_MCP_SOCKET": str(tmp_path / "none.sock"),
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ["HOME"],
        },
        capture_output=True,
        timeout=15,
    )
    assert out.returncode == 2
    assert b"install-agent" in out.stderr
```

- [ ] **Step 2: Write `docs/DAEMON.md`**

Contents (write in full): the two modes; `install-agent` walkthrough (build with `--sign "Developer ID Application: Andrei M. Lavrenov (VUMUR696L9)"`, copy to `/Applications`, run `macos-apps-mcp install-agent`, approve each prompt, FDA drag); the **manual acceptance checklist** — grant once via daemon, then from (a) Terminal shim, (b) Claude Desktop shim config, (c) VS Code shim config run a calendar read, a mail read, a chat.db-backed read — all succeed with zero re-prompts; hardened-runtime check (`codesign -dvv` shows `runtime`; pyobjc imports fine — else add `allow-unsigned-executable-memory` per spec §A); troubleshooting (`launchctl print gui/$UID/ren.lav.macos-apps-mcp`, Login Items toggle, log locations); uninstall.

- [ ] **Step 3: Run the automated integration slice on-device**

Run: `uv run pytest -m integration -k daemon -v`
Expected: 3 passed on this Mac. Record the results. Then follow docs/DAEMON.md for the signed build + manual acceptance checklist (human-in-the-loop — coordinate with Andrei).

- [ ] **Step 4: Full gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_daemon_integration.py docs/DAEMON.md
git commit -m "test(daemon): on-device integration + DAEMON.md install/acceptance guide (#71)"
```

---

## Notes for the implementer

- **`fastmcp` pin:** repo pins `fastmcp>=2.0`; installed is 3.4.2 — `http_app`, `create_proxy`, `StreamableHttpTransport(httpx_client_factory=…)` are 3.x APIs (spike-verified on 3.4.2). If an import fails, check the installed version first, do not vendor shims.
- **uvicorn `fd=`:** hand the daemon's own bound fd to `uvicorn.Config`; passing `uds=` instead would re-bind `0666` and break the perms contract (Task 1's whole point).
- **Do not add lifecycle guards to the daemon role** — `install_lifecycle_guards()` is the stdio orphan-watcher; launchd `KeepAlive` owns the daemon.
- **SMAppService status ints** are from `ServiceManagement.h` (`SMAppServiceStatusNotRegistered=0, Enabled=1, RequiresApproval=2, NotFound=3`).
- The bundle smoke (`env -i … -c "import macos_apps_mcp"`) is the canary for the getpath layout claim (stdlib at `Contents/lib/python3.14`). If it fails, fall back to setting `PYTHONHOME` in the LaunchAgent plist + client snippet env — spec allows it; note it in DAEMON.md.
