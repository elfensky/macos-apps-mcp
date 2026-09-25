"""#56 acceptance: every osascript template carries a balanced `with timeout`.

Introspective (not a hardcoded list) so a NEW template added later with a `tell
application` block but no `with timeout` fails this test — the guard can't rot.

GATE-10: a second tripwire, over every ``run_osascript`` CALL SITE rather than every
template. A script's own ``with timeout`` block can self-abort the Apple Event *before*
the host-side ``timeout=`` cap the caller passed to ``runtime.run_osascript`` would ever
fire (#140/dedupe: ``_DEDUPE_TIMEOUT = 900.0`` but the script backstop was
``with timeout of 600 seconds`` — the host cap never got a chance to matter). The
invariant is: **the script's own backstop must be >= the host cap that gates it.**

``_call_sites()`` walks every adapter module (``macos_apps_mcp/adapters/*.py``, minus
``__init__.py``) plus ``macos_apps_mcp/doctor.py``, finds every call whose callee is
(qualified or unqualified) ``run_osascript``, and resolves:

- the TEMPLATE string passed as the first positional argument — a bare name looked up
  on the calling module, or a ``module.NAME`` attribute chain (one level, matching the
  ``from . import mail_drafts`` + ``mail_drafts._DELETE_DRAFT`` shape actually used);
- the HOST CAP — the ``timeout=`` keyword's literal or module-attribute value, or
  ``runtime._OSASCRIPT_TIMEOUT`` (30s) when the keyword is absent;
- the SCRIPT BACKSTOP — the integer N of the first ``with timeout of N seconds`` at or
  after the template's ``on run`` line (a handler's own ``with timeout`` block, like
  ``mail_addressing.MAILBOX_REF``'s 120s ``mailboxFor`` wrapper, sits BEFORE ``on run``
  and does not count — it bounds one handler call, not the whole script).

Anything the resolver cannot pin down — an unresolvable template expression, a
non-string template, a timeout keyword of another shape, no ``with timeout`` at or
after ``on run`` — is a FAILING case that names ``file:line``, never a skip. GATE-10's
"empty edge": a template with no ``with timeout`` at all already fails
``test_every_osascript_template_carries_with_timeout`` above; here it also fails
closed rather than silently passing.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pathlib
import pkgutil
import re

import pytest

import macos_apps_mcp.adapters as adapters_pkg
from macos_apps_mcp import runtime


def _osascript_templates():
    """(label, source) for each module-level string that drives an app via osascript."""
    for mod_info in pkgutil.iter_modules(adapters_pkg.__path__):
        mod = importlib.import_module(f"macos_apps_mcp.adapters.{mod_info.name}")
        for name in dir(mod):
            val = getattr(mod, name)
            if isinstance(val, str) and "tell application" in val and "\n" in val:
                yield f"{mod_info.name}.{name}", val


def test_templates_are_discovered():
    # guard the introspection itself — an empty sweep would make the checks vacuous.
    labels = [label for label, _ in _osascript_templates()]
    assert len(labels) >= 10, labels


def test_every_osascript_template_carries_with_timeout():
    for label, tpl in _osascript_templates():
        assert "with timeout of" in tpl, f"{label} has no `with timeout` (#56)"
        # balanced open/close so a mis-edit can't leave a half-wrapped block
        assert tpl.count("with timeout of") == tpl.count("end timeout"), (
            f"{label} has unbalanced with timeout / end timeout"
        )


# --- GATE-10: script backstop >= host cap over every call site -------------------


class _Unresolved(Exception):
    """The resolver could not pin down a template, backstop, or host cap."""


_ADAPTERS_DIR = pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "adapters"
_DOCTOR_PATH = pathlib.Path(__file__).parent.parent / "macos_apps_mcp" / "doctor.py"

_ON_RUN_RE = re.compile(r"\bon run\b")
_WITH_TIMEOUT_RE = re.compile(r"with timeout of (\d+) seconds")


def _source_files():
    """(path, dotted module name) for every adapter module (minus __init__) + doctor."""
    for path in sorted(_ADAPTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        yield path, f"macos_apps_mcp.adapters.{path.stem}"
    yield _DOCTOR_PATH, "macos_apps_mcp.doctor"


def _is_run_osascript_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "run_osascript"
    if isinstance(func, ast.Attribute):
        return func.attr == "run_osascript"
    return False


def _expr_label(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_expr_label(node.value)}.{node.attr}"
    return f"<{type(node).__name__}>"


def _resolve_expr(node: ast.expr, module):
    """Resolve a bare Name (module attribute) or one-level `mod.NAME` chain."""
    if isinstance(node, ast.Name):
        if not hasattr(module, node.id):
            raise _Unresolved(f"{module.__name__!r} has no attribute {node.id!r}")
        return getattr(module, node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve_expr(node.value, module)
        if not hasattr(base, node.attr):
            raise _Unresolved(
                f"{_expr_label(node.value)!r} has no attribute {node.attr!r}"
            )
        return getattr(base, node.attr)
    raise _Unresolved(f"unsupported expression shape: {ast.dump(node)}")


def _resolve_backstop(template) -> int:
    """The first `with timeout of N seconds` at/after `on run`, else the first."""
    if not isinstance(template, str):
        raise _Unresolved(f"template is not a string: {template!r}")
    lines = template.splitlines()
    on_run_idx = next(
        (i for i, line in enumerate(lines) if _ON_RUN_RE.search(line)), None
    )
    search_lines = lines[on_run_idx:] if on_run_idx is not None else lines
    for line in search_lines:
        m = _WITH_TIMEOUT_RE.search(line)
        if m:
            return int(m.group(1))
    where = "at or after 'on run'" if on_run_idx is not None else "in the template"
    raise _Unresolved(f"no `with timeout of N seconds` found {where}")


def _resolve_host_cap(call: ast.Call, module) -> float:
    for kw in call.keywords:
        if kw.arg != "timeout":
            continue
        value = kw.value
        if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            return float(value.value)
        if isinstance(value, ast.Name):
            resolved = _resolve_expr(value, module)
            if not isinstance(resolved, (int, float)):
                raise _Unresolved(f"timeout= resolved to non-numeric {resolved!r}")
            return float(resolved)
        raise _Unresolved(f"unsupported timeout= expression shape: {ast.dump(value)}")
    return float(runtime._OSASCRIPT_TIMEOUT)


@dataclasses.dataclass(frozen=True)
class _CallSite:
    id: str
    template_label: str
    backstop: float | None
    host: float | None
    error: str | None


def _call_sites() -> list[_CallSite]:
    sites: list[_CallSite] = []
    for path, modname in _source_files():
        module = importlib.import_module(modname)
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_run_osascript_call(node.func):
                continue
            if not node.args:
                sites.append(
                    _CallSite(
                        id=f"{path.name}:{node.lineno}:<no-template-arg>",
                        template_label="<none>",
                        backstop=None,
                        host=None,
                        error="run_osascript call has no positional template argument",
                    )
                )
                continue
            template_node = node.args[0]
            label = _expr_label(template_node)
            site_id = f"{path.name}:{node.lineno}:{label}"
            try:
                template = _resolve_expr(template_node, module)
                backstop = _resolve_backstop(template)
                host = _resolve_host_cap(node, module)
            except _Unresolved as exc:
                sites.append(_CallSite(site_id, label, None, None, str(exc)))
                continue
            sites.append(_CallSite(site_id, label, backstop, host, None))
    # stable ids regardless of filesystem glob order
    return sorted(sites, key=lambda s: s.id)


_CALL_SITES = _call_sites()


def test_call_sites_are_discovered():
    # guard the walk itself — a broken one would make every check below vacuous.
    ids = [s.id for s in _CALL_SITES]
    assert len(ids) >= 40, ids
    assert any(s.startswith("mail.py:") and s.endswith(":_DEDUPE") for s in ids), ids
    assert any(s.startswith("doctor.py:") and s.endswith(":_PROBE") for s in ids), ids


@pytest.mark.parametrize("site", _CALL_SITES, ids=lambda s: s.id)
def test_every_call_site_backstop_covers_host_cap(site: _CallSite):
    if site.error is not None:
        pytest.fail(f"{site.id}: {site.error}")
    assert site.backstop >= site.host, (
        f"{site.id}: script backstop {site.backstop}s < host cap {site.host}s — "
        "the script can self-abort before the host-side timeout ever fires (GATE-10)"
    )
