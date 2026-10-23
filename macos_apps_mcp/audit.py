"""Write-audit trail + per-tool usage tally (#67) — one module owns the audit concept.

Three parts, one seam:
- **storage** — append-only JSONL under the XDG state dir (rotation, bounded reads;
  never raises: auditing must not fail a user's write);
- **record schema** — what an audit envelope looks like (op, truncated args,
  resolved dry_run, client caller, before/after pointers);
- **AuditMiddleware** — the central seam: logs an envelope for EVERY tool named in its
  audit-verb map, with before-state captured only for id-addressed update/delete/
  complete tools. Adapters hold no audit logic; before-state comes through the
  ``Snapshotter`` Protocol (contracts.py). The middleware ACCEPTS its audit-verb map
  and snapshot sources at construction — dependencies accepted, not created — so tests
  build one with fakes instead of patching server globals. GATE-06: a write is a KEY
  of ``audit_verbs``, so a write cannot be tracked without a verb — there is no
  generic ``"write"`` fallback (the former ``_audit_op`` prefix table this replaces).
  ``registry.py`` (server.py's one registration record per tool) fills the map at
  registration; this middleware only reads it, per call. server.py wires it after
  tool registration, with the registry its decorators populated (the middleware also
  reads it per call, so wiring order can never silently drop coverage).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

import anyio
from fastmcp.server.middleware import Middleware

# pydantic arrives through mcp's declared `pydantic>=2.11,<3` (>=2.12 on Python 3.14).
# pyproject.toml is not edited: version.yml fails a PR that edits it without a bump.
from pydantic import TypeAdapter, ValidationError

from .contracts import Snapshotter
from .text import SUMMARY_MAX, sanitize_line

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


def audit_write(record: dict) -> bool:
    """Append one JSON record to the audit log. NEVER raises — auditing must not fail a
    user's write, so a logging error (disk full, permission, missing dir) is
    swallowed. Returns True after the append, False when the write failed; callers
    may ignore the value (the dashboard shows a lost record, #430)."""
    try:
        path = _audit_path()
        if path.exists() and path.stat().st_size > _AUDIT_MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))  # rotate; one backup
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — audit must never break a write
        log.debug("audit_write failed: %s", e)
        return False
    return True


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
    for line in text.split("\n"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # skip a truncated/corrupt line, never fail the read
        if not isinstance(rec, dict):
            continue  # a JSON line that is no record (``true``, a list) is corrupt too
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


def read_all() -> list[dict]:
    """Every audit record, ``audit.jsonl.1`` then ``audit.jsonl``, oldest to newest:
    the dashboard's reader (D-12). No cache and no limit: the whole log is two plain
    file reads. A missing file contributes nothing and a corrupt line is skipped; an
    unreadable file adds one ``{"error": …}`` entry so the page can say so (never an
    empty list masquerading as "no writes"). ``audit_read`` and the ``audit`` tool are
    deliberately unchanged."""
    live = _audit_path()
    out: list[dict] = []
    for path in (live.with_name(live.name + ".1"), live):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.debug("read_all failed: %s", e)
            out.append({"error": f"audit log unreadable: {e}"})
            continue
        for line in text.split("\n"):
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # a truncated/corrupt line never fails the read
            if isinstance(rec, dict):
                out.append(rec)
    return out


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
    for line in text.split("\n"):
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


def usage_report(registered: Iterable[str]) -> dict:
    """The full ``usage`` tool report from the tally + the registered-tool names
    (C5b — report logic lives here, the tool is a one-line delegation): ``tools``
    busiest-first, ``never_used`` (registered minus called — the pruning list),
    ``total_calls``."""
    tally = usage_read()
    tools = sorted(
        ({"tool": t, **stats} for t, stats in tally.items()),
        key=lambda e: e["count"],
        reverse=True,
    )
    return {
        "tools": tools,
        "never_used": sorted(set(registered) - tally.keys()),
        "total_calls": sum(e["count"] for e in tally.values()),
    }


# --- record schema -----------------------------------------------------------------


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


def _audit_receipt(result) -> str | None:
    """The batch ``receipt`` a recoverable Mail write returned, if any: the exact link
    from its middleware line to the plan and done records (D-12)."""
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        inner = sc.get("result", sc)  # the same unwrap as _audit_after
        if isinstance(inner, dict) and isinstance(inner.get("receipt"), str):
            return inner["receipt"]
    return None


def _safe_snapshot(source: Snapshotter, ident: str) -> dict | None:
    try:
        p = source.snapshot(ident)
        return p.as_dict() if p is not None else None
    except Exception:  # noqa: BLE001 — audit must never break a write
        return None


_BOOL = TypeAdapter(bool)  # the coercion the tool's own validation applies to dry_run
_FALLBACK_CALLER = "unknown-client"


def resolve_dry_run(tool: str, args: Mapping, defaults: Mapping[str, bool]) -> bool:
    """The ``dry_run`` the tool will act on (#222): the client's value coerced as
    pydantic coerces it for the tool (``"false"`` is False), else the signature default;
    a tool with no ``dry_run`` parameter always acts. The middleware runs BEFORE that
    validation, so a rejected value falls back to the default — the call then fails
    and no record is written."""
    default = defaults.get(tool, False)
    if "dry_run" not in args:
        return default
    try:
        return _BOOL.validate_python(args["dry_run"])
    except ValidationError:
        return default


def _label(text: object) -> str:
    """One line, control-free, at most ``SUMMARY_MAX`` characters — a hard cut, since
    ``clean_summary`` appends a ``[truncated N chars]`` marker past the bound."""
    return sanitize_line(text)[:SUMMARY_MAX]


def _caller(context) -> tuple[str, str | None]:
    """``("<name> <version>", shim id | None)`` from the MCP client's ``clientInfo``.

    Advisory labels, reported by the client: never an identity check, never a gate.
    A context without ``fastmcp_context`` (in-process call, test double), without a
    session, or without ``clientInfo`` gives the fixed fallback."""
    try:
        info = context.fastmcp_context.session.client_params.clientInfo
        caller = _label(f"{info.name} {info.version}")
        session = _label(getattr(info, "session", None) or "")
    except (AttributeError, RuntimeError):
        return _FALLBACK_CALLER, None
    return caller or _FALLBACK_CALLER, session or None


# --- middleware ----------------------------------------------------------------------


class AuditMiddleware(Middleware):
    """Append an audit record for every write; capture before-state on update/delete
    (#67). Central seam — adapters hold no audit logic. All failures are swallowed.

    ``audit_verbs`` (a tool name -> its audit-log verb) and ``snapshot_sources`` are
    registries owned by the caller (``registry.py`` fills them during registration,
    via server.py's ``_tool`` decorator, before it wires this middleware); the
    middleware reads them per call, so construction order can't break it either way.
    A tool is a write IFF it is a key of ``audit_verbs`` — the map both selects what
    gets logged and states under which verb (GATE-06: no separate write-tool set, and
    no generic ``"write"`` fallback for a verb the caller forgot to state).

    Every record carries ``dry_run``, resolved from ``dry_run_defaults`` (a tool name ->
    its signature default) when the caller omitted it; ``args`` stay as the client sent
    them. ``caller`` (and ``session``, for a shim) are advisory client labels.
    """

    def __init__(
        self,
        audit_verbs: Mapping[str, str],
        snapshot_sources: dict[str, Snapshotter],
        dry_run_defaults: Mapping[str, bool] | None = None,
    ) -> None:
        self._audit_verbs = audit_verbs
        self._snapshot_sources = snapshot_sources
        self._dry_run_defaults = dry_run_defaults or {}

    async def on_call_tool(self, context, call_next):
        tool = context.message.name
        usage_log(tool)  # tally every call (reads included) — swallows its own errors
        args = dict(context.message.arguments or {})
        dry_run = resolve_dry_run(tool, args, self._dry_run_defaults)
        caller, session = _caller(context)
        before = None
        source = self._snapshot_sources.get(tool)
        if source is not None and args.get("id"):
            before = await anyio.to_thread.run_sync(_safe_snapshot, source, args["id"])
        # The snapshot above is a SECOND native read on top of whatever the write does
        # (delete_draft: one `_DRAFTS` spawn here, one `_DELETE_DRAFT` spawn in the
        # adapter — two, not the three #161 estimated; dry-run is also two). #161 asked
        # whether the write should hand its own before-state over so this could be
        # skipped. MEASURED 2026-08-11 on the real Drafts mailbox: 638/652/653 ms, and
        # it is bounded — `_DRAFTS` stops at 25 records, so it is osascript spawn cost,
        # not O(mailbox). Not worth it: ~0.65s on a human-paced tool against reshaping
        # the seam EVERY adapter's audit trail runs through, plus teaching one script to
        # rebuild the exact Pointer this produces or the record silently changes shape.
        # before-state is what makes mail_undo and the audit log trustworthy; it does
        # not get cheapened for a spawn. Revisit only if a batch write lands here.
        result = await call_next(context)
        if tool in self._audit_verbs and not result.is_error:
            try:
                after = _audit_after(result)
                receipt = _audit_receipt(result)
                audit_write(
                    {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "tool": tool,
                        "op": self._audit_verbs[tool],
                        "args": _audit_args(args),
                        "dry_run": dry_run,
                        "caller": caller,
                        **({"session": session} if session is not None else {}),
                        "target_id": args.get("id") or (after or {}).get("id"),
                        "before": before,
                        "after": after,
                        **({"receipt": receipt} if receipt else {}),
                    }
                )
            except Exception:  # noqa: BLE001 — audit must never break a write
                pass
        return result
