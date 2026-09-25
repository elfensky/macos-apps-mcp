# Technology Stack

**Analysis Date:** 2026-08-28

## Languages

**Primary:**
- Python 3.11+ - Core server and adapter implementations; min version enforced in `pyproject.toml`
- PyObjC 10.0+ - Bridge to native macOS frameworks (EventKit, Foundation, ServiceManagement)
- AppleScript - Called via `osascript` for Mail, Notes, Contacts, Photos, Safari, Messages, Shortcuts adapters

**Secondary:**
- Shell (bash/zsh) - Build scripts (`scripts/build_app.sh` for app bundling)
- Plist XML - Configuration files and LaunchAgent plist (`packaging/ren.lav.macos-apps-mcp.plist`)

## Runtime

**Environment:**
- Python 3.11, 3.12, 3.13 (tested; see `pyproject.toml` classifiers)
- macOS 12+ (EventKit thread-affinity + TCC requirements)
- Single-threaded worker model: `concurrent.futures.ThreadPoolExecutor(max_workers=1)` in `macos_apps_mcp/runtime.py` (line 54) — ALL EventKit and osascript calls serialized through one dedicated thread to handle thread affinity and TCC authorization

**Package Manager:**
- `uv` (Astral's modern Python package manager)
- Lockfile: `uv.lock` (deterministic dependency resolution)
- Entry point: `python -m macos_apps_mcp` (via `macos_apps_mcp/__main__.py`)

## Frameworks

**Core:**
- **FastMCP 2.0+** (unbounded `>=2.0`, currently 3.x) — Lightweight MCP server abstraction in `macos_apps_mcp/server.py`; thin dispatch layer with tool registration decorators
- **uvicorn 0.30+** — ASGI server used only in daemon mode (`macos_apps_mcp/daemon.py`, line 16) for unix domain socket serving; skipped in stdio mode

**Native Bridge:**
- **PyObjC Framework: EventKit 10.0+** — Calendar and Reminders access via `EKEventStore`, `EKEvent`, `EKReminder` (adapters: `macos_apps_mcp/adapters/calendar.py`, `macos_apps_mcp/adapters/reminders.py`)
- **PyObjC Framework: Cocoa (Foundation) 10.0+** — Core macOS utilities (`NSBundle`, file handling, imports in `macos_apps_mcp/runtime.py`, line 35)
- **PyObjC Framework: ServiceManagement 10.0+** — LaunchAgent registration via `SMAppService` in daemon mode (`macos_apps_mcp/deploy.py`, line 55-57)

**Testing:**
- pytest 8.x, <10 — Unit test runner with markers for integration tests
- pytest-cov 6.x, <8 — Coverage reporting
- Mock at adapter boundary (typed-Protocol fakes, no native calls in unit tests; integration tests marked `@pytest.mark.integration`)

**Build/Dev:**
- **ruff 0.15+, <0.17** — Unified linter + formatter; rules: `E, F, I, UP, B, SIM`; line-length 88 (config in `pyproject.toml`, lines 67-75)
- **hatchling** — Build backend (wheel + sdist)

## Key Dependencies

**Critical:**
- **mcp 1.26+** — Official MCP SDK; used directly for `mcp.types` in `macos_apps_mcp/server.py` (line 33)
- **anyio 4.x+** — Async utility library, imported directly in `macos_apps_mcp/audit.py` (noted in `pyproject.toml` comment line 32)
- **httpx 0.27+** — HTTP client with unix socket support for daemon shim↔daemon communication (`macos_apps_mcp/daemon.py`, line 15); **critical timeout tuning**: `Timeout(None, connect=10.0)` to prevent premature read-stream closure on long-running operations (issue #170)

**Infrastructure:**
- **cryptography, joserfc (via authlib 1.7.2)** — Transitive deps; authlib used by fastmcp's request signing
- **beartype** — Runtime type checking (fastmcp dependency)
- **cachetools** — Caching utility (transitive, fastmcp)

**Not Used (by design):**
- No ORM (direct sqlite3 for read-only data planes)
- No web framework beyond FastMCP/uvicorn
- No mypy (Protocol-based architecture eliminates need; same pattern as sibling repos `lintle`, `descent-engine`)

## Configuration

**Environment Variables:**
- `MACOS_APPS_READ_ONLY=1` — Disables all write and send tools at registration time (`macos_apps_mcp/server.py`); safe-deploy guard
- `MACOS_APPS_ALLOW_SEND` — Comma-separated adapter list (e.g. `mail,messages`) enabling outbound send tools; daemon reads once at startup; shim clients read from `~/.local/state/macos-apps-mcp/allow_send` file (`macos_apps_mcp/deploy.py`, line 139)
- `MACOS_APPS_MCP_SOCKET` — Override unix socket path for daemon mode (default: `~/.local/state/macos-apps-mcp/daemon/mcp.sock`)
- `PYTHON*`, `PYTHONPATH` — Explicitly ignored in daemon mode via bundle's `-E -s -P` flags to prevent environment shadowing

**Build Configuration:**
- `pyproject.toml` — Project metadata, dependencies, ruff/pytest config
- `packaging/Info.plist` — macOS app metadata (CFBundleIdentifier: `ren.lav.macos-apps-mcp`, CFBundleShortVersionString version bump)
- `packaging/entitlements.plist` — Code signing entitlements (hardened runtime, optional escape hatch in docs/DAEMON.md line 208)
- `.github/workflows/publish.yml` — CI/CD pipeline for PyPI publishing

## Platform Requirements

**Development:**
- macOS 12+ (Ventura or later preferred for TCC/launchd stability)
- Xcode Command Line Tools (for code signing, `codesign` + `xcrun notarytool`)
- Python 3.11+ installed (test matrix covers 3.11, 3.12, 3.13)
- `uv` (installed via `curl -LsSf https://astral.sh/uv/install.sh | sh` or Homebrew)

**Production:**
- macOS 12+ (same as dev)
- Deployment via:
  - **Stdio mode (dev/CI):** venv Python runs `python -m macos_apps_mcp` per MCP client, managed by MCP SDK startup
  - **Daemon mode (production):** Signed, notarized `.app` bundle in `/Applications`, registered with launchd via `SMAppService`, spawns one persistent process serving multiple clients over unix socket; installed via `macos-apps-mcp install-agent`

## Publishing

**PyPI:**
- **Package:** `macos-apps-mcp`
- **Indexes:** PyPI (production) + TestPyPI (staging)
- **Auth:** Trusted Publishing (OIDC via GitHub Actions) — no stored tokens
- **Build:** Pure-Python sdist + wheel (macOS-only testing; EventKit imports optional in wheel)
- **Publish flow:** Push to `main` → auto-publish to TestPyPI; manual `workflow_dispatch` → choice of testpypi or pypi (line 20-28, `.github/workflows/publish.yml`)

**Daemon Distribution:**
- **Not on PyPI.** Built locally via `scripts/build_app.sh`, signed with Developer ID, optionally notarized, attached to GitHub releases as `.zip`
- **Bundle executable** (`macos-apps-mcp.app/Contents/MacOS/macos-apps-mcp`): compiled Python app via PyInstaller-like bundling (vendor chain: `.app/Contents/Resources/venv` or similar; see `docs/DAEMON.md` line 105)

---

*Stack analysis: 2026-08-28*
