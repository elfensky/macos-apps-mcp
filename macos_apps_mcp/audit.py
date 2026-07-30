"""Write-audit trail + per-tool usage tally (#67) — one module owns the audit concept.

Three parts, one seam:
- **storage** — append-only JSONL under the XDG state dir (rotation, bounded reads;
  never raises: auditing must not fail a user's write);
- **record schema** — what an audit envelope looks like (op, truncated args,
  before/after pointers);
- **AuditMiddleware** — the central seam: logs an envelope for EVERY write tool, with
  before-state captured only for id-addressed update/delete/complete tools. Adapters
  hold no audit logic; before-state comes through the ``Snapshotter`` Protocol
  (contracts.py). The middleware ACCEPTS its write-tool set and snapshot sources at
  construction — dependencies accepted, not created — so tests build one with fakes
  instead of patching server globals. server.py wires it after tool registration, with
  registries its decorators populated (the middleware also reads them per call, so
  wiring order can never silently drop coverage).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import anyio
from fastmcp.server.middleware import Middleware

from .contracts import Snapshotter

log = logging.getLogger("macos_apps_mcp")

# --- storage ---------------------------------------------------------------------

AUDIT_LIMIT = 50
_AUDIT_MAX_BYTES = 5 * 1024 * 1024  # rotate past ~5 MB; one backup


def state_dir() -> Path:
    """The XDG state dir for this server, created on use."""
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    d = Path(base) / "macos-apps-mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audit_path() -> Path:
    return state_dir() / "audit.jsonl"


def audit_write(record: dict) -> None:
    """Append one JSON record to the audit log. NEVER raises — auditing must not fail a
    user's write, so a logging error (disk full, permission, missing dir) is
    swallowed."""
    try:
        path = _audit_path()
        if path.exists() and path.stat().st_size > _AUDIT_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))  # rotate; one backup
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — audit must never break a write
        log.debug("audit_write failed: %s", e)


def _instant(ts) -> datetime | None:
    """Parse an ISO datetime string into an aware instant; a naive value is taken as
    LOCAL time (the only form ``audit_write`` writes). None when unparseable."""
    try:
        return datetime.fromisoformat(ts).astimezone()
    except (ValueError, TypeError):
        return None


def audit_read(since: str | None = None, limit: int = AUDIT_LIMIT) -> list[dict]:
    """Recent audit entries, newest first, at most ``limit``. ``since`` (ISO datetime)
    drops older entries by INSTANT compare, not string compare: entries are written
    naive-local, but the audit tool tells the model to ground ``since`` via now() —
    which returns an offset-carrying ISO string, and lexically ``…T12:00:00`` <
    ``…T12:00:00+02:00`` silently dropped boundary entries. Unparseable values fall
    back to the old lexical compare. Malformed lines are skipped; a missing log is
    empty. NEVER raises: an unreadable log yields a single explicit error entry —
    never a raw ``OSError``, and never an empty list masquerading as "no writes"."""
    path = _audit_path()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.debug("audit_read failed: %s", e)
        return [{"error": f"audit log unreadable: {e}"}]
    since_i = _instant(since) if since else None
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # skip a truncated/corrupt line, never fail the read
        if since:
            ts = rec.get("ts", "")
            rec_i = _instant(ts) if ts else None
            if since_i is not None and rec_i is not None:
                if rec_i < since_i:
                    continue
            elif str(ts) < since:
                continue
        out.append(rec)
    out.reverse()  # newest first
    return out[:limit]


# --- per-tool usage tally (#67 addendum) -------------------------------------------
# ponytail: append-only jsonl, aggregate on read — mirrors the audit log. Timestamps
# preserved so "how often" is a real rate, not just a total. Rotates like audit.


def _usage_path() -> Path:
    return state_dir() / "usage.jsonl"


def usage_log(tool: str) -> None:
    """Append one usage record for a tool call. NEVER raises — usage tracking must not
    fail a user's call, so any logging error is swallowed."""
    try:
        path = _usage_path()
        if path.exists() and path.stat().st_size > _AUDIT_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))  # rotate; one backup
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "tool": tool}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001 — tracking must never break a call
        log.debug("usage_log failed: %s", e)


def usage_read() -> dict[str, dict]:
    """Per-tool tally from the usage log: ``{tool: {"count", "first", "last"}}``.
    Malformed lines are skipped; a missing log is empty. NEVER raises: an unreadable
    log reads as empty (logged) — a lost tally must not fail the ``usage`` tool."""
    path = _usage_path()
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.debug("usage_read failed: %s", e)
        return out
    for line in text.splitlines():
        try:
            rec = json.loads(line)
            tool, ts = rec["tool"], rec.get("ts", "")
        except (ValueError, KeyError, TypeError):
            continue  # skip a truncated/corrupt line, never fail the read
        entry = out.get(tool)
        if entry is None:
            out[tool] = {"count": 1, "first": ts, "last": ts}
        else:
            entry["count"] += 1
            if ts:
                entry["last"] = ts
    return out


# --- record schema -----------------------------------------------------------------


def _audit_op(tool: str) -> str:
    for prefix in ("create", "update", "delete"):
        if tool.startswith(prefix):
            return prefix
    return {
        "complete_reminder": "complete",
        "run_shortcut": "action",
        "safari_open": "open",
        "mail_reply": "reply",
        # outbound — distinct from the generic "write" so the audit log is filterable
        # for "what actually left this machine" (M3 review; the log is one of the
        # three things carrying consent for a send).
        "send_mail": "send",
        "reply_all": "send",
        "forward_mail": "send",
    }.get(tool, "write")


def _audit_args(args: dict) -> dict:
    # truncate long string values so a big note body can't bloat the log
    return {
        k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
        for k, v in args.items()
    }


def _audit_after(result) -> dict | None:
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        inner = sc.get("result", sc)  # FastMCP may wrap a scalar under "result"
        if isinstance(inner, dict) and "id" in inner:
            return inner
    return None


def _safe_snapshot(source: Snapshotter, ident: str) -> dict | None:
    try:
        p = source.snapshot(ident)
        return p.as_dict() if p is not None else None
    except Exception:  # noqa: BLE001 — audit must never break a write
        return None


# --- middleware ----------------------------------------------------------------------


class AuditMiddleware(Middleware):
    """Append an audit record for every write; capture before-state on update/delete
    (#67). Central seam — adapters hold no audit logic. All failures are swallowed.

    ``write_tools`` and ``snapshot_sources`` are registries owned by the caller
    (server.py's tool decorators fill them during registration, before it wires this
    middleware); the middleware reads them per call, so construction order can't
    break it either way.
    """

    def __init__(
        self, write_tools: set[str], snapshot_sources: dict[str, Snapshotter]
    ) -> None:
        self._write_tools = write_tools
        self._snapshot_sources = snapshot_sources

    async def on_call_tool(self, context, call_next):
        tool = context.message.name
        usage_log(tool)  # tally every call (reads included) — swallows its own errors
        args = dict(context.message.arguments or {})
        before = None
        source = self._snapshot_sources.get(tool)
        if source is not None and args.get("id"):
            before = await anyio.to_thread.run_sync(_safe_snapshot, source, args["id"])
        result = await call_next(context)
        if tool in self._write_tools and not result.is_error:
            try:
                after = _audit_after(result)
                audit_write(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "tool": tool,
                        "op": _audit_op(tool),
                        "args": _audit_args(args),
                        "target_id": args.get("id") or (after or {}).get("id"),
                        "before": before,
                        "after": after,
                    }
                )
            except Exception:  # noqa: BLE001 — audit must never break a write
                pass
        return result
