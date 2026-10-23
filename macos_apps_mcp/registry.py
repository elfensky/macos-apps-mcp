"""One registration record per tool (GATE-04, GATE-06).

Every fact the dispatch layer, the middlewares, ``doctor`` and the tests need about a
tool is stated ONCE, at the decorator (``server.py``'s ``_tool``), and lands here as a
``ToolRecord``. The former hand-maintained name sets (``_WRITE_TOOLS``,
``_SNAPSHOT_SOURCES``, and ``audit.py``'s ``_audit_op`` prefix table) are *views* over
this dict — a new tool cannot silently miss any of them because there is no second
edit to forget.

A gated-off tool (read-only mode, a send-disabled adapter) still gets a record here,
with ``registered=False`` — never simply absent — so ``doctor``'s outbound report and
the tests can see the whole surface either way (GATE-04's elevation-of-privilege
mitigation: a record that says ``registered=False`` must never actually be reachable
through FastMCP).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from . import tiers
from .contracts import Snapshotter

Tier = Literal["read", "additive", "destructive", "send"]

_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "read": {"readOnlyHint": True, "destructiveHint": False},
    "additive": {"readOnlyHint": False, "destructiveHint": False},
    "destructive": {"readOnlyHint": False, "destructiveHint": True},
    "send": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
}


@dataclass(frozen=True)
class ToolRecord:
    name: str
    tier: Tier
    adapter: str | None  # the adapter the body dispatches to; None = meta tool
    permission: tuple[str, ...]  # macOS grants the docstring must name; () = none
    audit_verb: str | None  # audit-log "op" for a write; None for a read
    notice: bool  # untrusted-data notice (#53) rides the result
    backup_notice: bool  # #163 storage advisory rides the result
    # GATE-05 (D-04): "removes or replaces content" — already the UNION with the
    # delete_* prefix rule by the time it lands here (_tool composes it before
    # calling add()), so a tool merely NAMED delete_* is in the class even when its
    # own call site forgets to say so. Never read this field alone to decide
    # membership from scratch; registry.removes_content_tools() and the D-04 test
    # both re-apply the prefix rule on top of it, on purpose (a builder bug must not
    # silently hide a delete_* tool from the fail-closed check).
    removes_content: bool
    snapshot: Snapshotter | None  # before-state source for an id-addressed write
    open_world: bool  # MAY reach off-machine without being outbound-by-design
    registered: bool  # False when a gate (READ_ONLY / ALLOW_SEND) skipped it
    fn: Callable[..., object]  # the dispatched function, for introspection

    @property
    def is_write(self) -> bool:
        return self.tier != "read"

    @property
    def annotations(self) -> dict[str, bool]:
        ann = dict(_ANNOTATIONS[self.tier])
        if self.open_world:
            ann["openWorldHint"] = True
        return ann


TOOLS: dict[str, ToolRecord] = {}


def derive_audit_verb(name: str, tier: Tier, explicit: str | None) -> str | None:
    """Reads carry no verb. Sends are always ``"send"``. Otherwise the
    create/update/delete/complete prefix — and if none applies the caller MUST supply
    ``explicit``, so a new write cannot land in a silent generic bucket. No
    ``"write"`` fallback (GATE-06; CONTEXT.md requires the ``_audit_op`` fallback
    gone, not kept)."""
    if tier == "read":
        if explicit is not None:
            raise TypeError(f"{name}: a read tool carries no audit verb")
        return None
    if explicit is not None:
        return explicit
    if tier == "send":
        return "send"
    for prefix in ("create", "update", "delete", "complete"):
        if name.startswith(prefix):
            return prefix
    raise TypeError(f"{name}: write tool needs an explicit audit= verb")


def add(rec: ToolRecord) -> ToolRecord:
    """Store ``rec`` — every tool gets exactly one record, ever (GATE-04 adjacency
    edge: a duplicate name is a bug caught at import, not a silent overwrite)."""
    if rec.name in TOOLS:
        raise TypeError(f"{rec.name}: registered twice")
    TOOLS[rec.name] = rec
    return rec


# --- derived views (what the hand tables used to be) ----------------------------------


def write_tools() -> frozenset[str]:
    """Every REGISTERED write — the set ``AuditMiddleware`` and the tests used to get
    from the hand-maintained ``_WRITE_TOOLS``."""
    return frozenset(n for n, r in TOOLS.items() if r.is_write and r.registered)


def snapshot_sources() -> dict[str, Snapshotter]:
    """Registered id-addressed writes -> their before-state adapter (was
    ``_SNAPSHOT_SOURCES``)."""
    return {
        n: r.snapshot
        for n, r in TOOLS.items()
        if r.snapshot is not None and r.registered
    }


def audit_verbs() -> dict[str, str]:
    """Registered writes -> their audit-log verb — the map ``AuditMiddleware`` keys
    on (GATE-06): a write with no verb here cannot exist, since ``derive_audit_verb``
    raises at registration rather than defaulting one in."""
    return {
        n: r.audit_verb
        for n, r in TOOLS.items()
        if r.audit_verb is not None and r.registered
    }


def _dry_run_default(fn) -> bool | None:
    """The ``dry_run`` default in ``fn``'s signature, or ``None`` when the tool has no
    ``dry_run`` parameter (or no default for it) — a tool that always acts."""
    param = inspect.signature(fn).parameters.get("dry_run")
    if param is None or param.default is inspect.Parameter.empty:
        return None
    return bool(param.default)


def dry_run_defaults() -> dict[str, bool]:
    """Every tool with an audit verb -> its signature ``dry_run`` default (#222), the
    map ``AuditMiddleware`` resolves an omitted ``dry_run`` from. Unlike ``audit_verbs``
    it does NOT filter on ``registered``: CI's ``MACOS_APPS_READ_ONLY=1`` pass and the
    send tools (off by default) must see the same map as a fully enabled server."""
    return {
        n: d
        for n, r in TOOLS.items()
        if r.audit_verb is not None and (d := _dry_run_default(r.fn)) is not None
    }


def no_notice() -> frozenset[str]:
    return frozenset(n for n, r in TOOLS.items() if not r.notice)


def backup_notice_tools() -> frozenset[str]:
    return frozenset(n for n, r in TOOLS.items() if r.backup_notice)


def removes_content_tools() -> frozenset[str]:
    """Every ALL-records (registered or not) tool that "removes or replaces
    content" (GATE-05, D-04) — the class the fail-closed dry-run-default test walks.
    Iterates every record, not just registered ones: a gated-off delete_* tool must
    still default dry_run=True on its underlying function, so it is correct the
    instant a gate reopens it."""
    return frozenset(
        n for n, r in TOOLS.items() if r.removes_content or n.startswith("delete_")
    )


def by_adapter(adapter: str) -> frozenset[str]:
    return frozenset(n for n, r in TOOLS.items() if r.adapter == adapter)


def adapter_names() -> list[str]:
    """The adapter names the registry holds, sorted; read per call (#430 IN-02)."""
    return sorted({r.adapter for r in TOOLS.values() if r.adapter})


def outbound_status() -> dict[str, list[str]]:
    """The two outbound facts that can DISAGREE (C6): ``registered`` = the adapters
    whose send tools actually got registered at import; ``configured`` = what the
    env/toggle enables RIGHT NOW. They diverge when ``macos-apps-mcp allow-send``
    writes the toggle but the daemon keeps running (deploy's "no daemon restarted"
    branch) — doctor reports the delta as ``outbound_pending`` with a restart
    directive.

    Card 2 (GATE-04, RESEARCH Pitfall 3): this is now the ONE outbound ledger — a view
    over the send records already sitting in ``TOOLS``, not a second hand-maintained
    set. ``tiers.py`` keeps only the pure gate predicates (``read_only``,
    ``allow_send``); this is the sole caller doctor and the tests read.

    ``configured`` also requires the adapter to be ON (PLAT-01): allow_send=mail with
    Mail OFF registers nothing, so reporting it would show a pending delta that no
    restart clears."""
    send_adapters = {r.adapter for r in TOOLS.values() if r.tier == "send"}
    registered = {
        r.adapter for r in TOOLS.values() if r.tier == "send" and r.registered
    }
    return {
        "registered": sorted(registered),
        "configured": sorted(
            a for a in send_adapters if tiers.allow_send(a) and tiers.adapter_enabled(a)
        ),
    }


def adapter_status() -> dict[str, list[str]]:
    """The adapter twin of ``outbound_status()`` (PLAT-01, D-03): ``registered`` = the
    adapters with at least one tool registered at import; ``configured`` = every
    adapter the deny-list (env/file) leaves ON right now. They diverge when the
    ``adapters_off`` file changes but the daemon keeps running — doctor reports the
    delta as ``adapters_pending`` with a restart directive. Every adapter has a read
    tool, so under ``MACOS_APPS_READ_ONLY`` an enabled adapter still shows up."""
    registered = {r.adapter for r in TOOLS.values() if r.adapter and r.registered}
    return {
        "registered": sorted(registered),
        "configured": sorted(n for n in adapter_names() if tiers.adapter_enabled(n)),
    }
