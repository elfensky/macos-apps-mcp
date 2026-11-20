"""#56 acceptance: every osascript template carries a balanced `with timeout`.

Introspective (not a hardcoded list) so a NEW template added later with a `tell
application` block but no `with timeout` fails this test — the guard can't rot.

GATE-10: a second tripwire, over every ``run_osascript`` CALL SITE rather than every
template. A script's own ``with timeout`` block can self-abort the Apple Event *before*
the host-side ``timeout=`` cap the caller passed to ``runtime.run_osascript`` would ever
fire (#140/dedupe: ``_DEDUPE_TIMEOUT = 900.0`` but the script backstop was
``with timeout of 600 seconds`` — the host cap never got a chance to matter). The
invariant is: **the script's own backstop must be >= the host cap that gates it.**

``_call_sites()`` walks every module of the package (``tests.scripts.modules()``, #581 —
the adapters, ``doctor`` and ``runtime`` alike), finds every call whose callee is
(qualified or unqualified) ``run_osascript``, and resolves:

- the TEMPLATE string passed as the first positional argument — a bare name looked up
  on the calling module, or a ``module.NAME`` attribute chain (one level, matching the
  ``from . import mail_drafts`` + ``mail_drafts._DELETE_DRAFT`` shape actually used);
- the HOST CAP — the ``timeout=`` keyword's literal, module-attribute value, or (#206,
  D-02) a CALL expression (``timeout=mail._act_timeout(len(located))``), resolved by
  calling the real function with ``mail_recover.MAX_TARGETS`` — the worst case the cap
  must cover, not whatever expression the call site happened to pass — or
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
import hashlib
import pathlib
import re

import pytest

from macos_apps_mcp import runtime
from macos_apps_mcp.adapters import mail_recover as _mail_recover_mod
from tests import scripts


def _osascript_templates():
    """(label, source) for each module-level string that drives an app via osascript."""
    yield from scripts.templates().items()


def test_templates_are_discovered():
    # guard the introspection itself — an empty sweep would make the checks vacuous.
    labels = [label for label, _ in _osascript_templates()]
    assert len(labels) >= scripts.MIN_TEMPLATES, labels
    # #581: the walk reaches past the adapters
    assert "runtime._WINDOW_INDEX" in labels, labels


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


_ON_RUN_RE = re.compile(r"\bon run\b")
_WITH_TIMEOUT_RE = re.compile(r"with timeout of (\d+) seconds")


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
        if isinstance(value, ast.Call):
            fn = _resolve_expr(value.func, module)
            if not callable(fn):
                raise _Unresolved(f"timeout= call target {fn!r} is not callable")
            # Evaluate at the worst case the cap must cover (MAX_TARGETS), never at
            # whatever expression the call site passed (e.g. `len(located)`) — GATE-10
            # asks "does the backstop cover the worst case", not "does it cover
            # whatever this particular call happened to pass".
            result = fn(_mail_recover_mod.MAX_TARGETS)
            if not isinstance(result, (int, float)):
                raise _Unresolved(f"timeout= call returned non-numeric {result!r}")
            return float(result)
        raise _Unresolved(f"unsupported timeout= expression shape: {ast.dump(value)}")
    return float(runtime._OSASCRIPT_TIMEOUT)


@dataclasses.dataclass(frozen=True)
class _CallSite:
    id: str
    template_label: str
    backstop: float | None
    host: float | None
    error: str | None
    source: str | None = None  # the script text; None when it could not be resolved


def _call_sites() -> list[_CallSite]:
    sites: list[_CallSite] = []
    for path, module in scripts.modules():
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
            sites.append(_CallSite(site_id, label, backstop, host, None, template))
    # stable ids regardless of filesystem glob order
    return sorted(sites, key=lambda s: s.id)


_CALL_SITES = _call_sites()


def test_call_sites_are_discovered():
    # guard the walk itself — a broken one would make every check below vacuous.
    ids = [s.id for s in _CALL_SITES]
    assert len(ids) >= scripts.MIN_CALL_SITES, ids
    assert any(s.startswith("mail.py:") and s.endswith(":_DEDUPE") for s in ids), ids
    assert any(s.startswith("doctor.py:") and s.endswith(":_PROBE") for s in ids), ids
    assert any(s.startswith("runtime.py:") for s in ids), ids  # #581


@pytest.mark.parametrize("site", _CALL_SITES, ids=lambda s: s.id)
def test_every_call_site_backstop_covers_host_cap(site: _CallSite):
    if site.error is not None:
        pytest.fail(f"{site.id}: {site.error}")
    assert site.backstop >= site.host, (
        f"{site.id}: script backstop {site.backstop}s < host cap {site.host}s — "
        "the script can self-abort before the host-side timeout ever fires (GATE-10)"
    )


def test_call_shaped_host_caps_are_evaluated_at_max_targets():
    # #206/D-02: `_MOVE`'s call site passes a CALL expression (`_act_timeout(n)`), not
    # a literal or a module-level constant — the resolver must evaluate the real
    # function at MAX_TARGETS (25), proving the shipped formula, not a re-derivation.
    sites = [
        s for s in _CALL_SITES if s.id.endswith(":_MOVE") and s.id.startswith("mail.py")
    ]
    assert sites, "no mail.py call site resolved for _MOVE"
    for site in sites:
        assert site.error is None, f"{site.id}: {site.error}"
        assert site.host == 435.0, f"{site.id}: host cap {site.host} != 435.0"


# --- #581: the guards are tied together -----------------------------------------------
#
# Two ways a script could miss a guard. A call-site script that is not in the compile
# inventory gets the timeout check but no compile check. A script that is run inline,
# by a call that starts ``osascript`` itself and not through ``runtime.run_osascript``,
# is in no inventory at all, so no guard sees it.


def _outside_inventory(sites) -> list[str]:
    """The ids of the call sites whose script is not a script of the inventory."""
    inventory = set(scripts.templates().values())
    return [site.id for site in sites if site.source not in inventory]


_PACKAGE = pathlib.Path(runtime.__file__).parent
# A string that starts osascript: the program alone (one item of an argument list, with
# or without a folder) or a command line with an option. A message that only names
# osascript ("osascript failed: …") is not a start.
_OSASCRIPT_START = re.compile(r"^(\S*/)?osascript( -|$)")
# Other ways to run a script without that string.
_OSASCRIPT_NAMES = frozenset({"MacOSXOSAScript", "NSAppleScript", "OSAScript"})
# The one door. Its scripts are the call sites above.
_OSASCRIPT_DOOR = "runtime.py:run_osascript"
# Each function outside the door that starts osascript: ``file:function`` -> (the hash
# of the function's source, why no script guard needs it). A change to the function
# fails the guard: read the change, then renew the hash (the failure prints it). Never
# an entry for a whole module.
_OSASCRIPT_PINNED = {
    # A `display alert` only (D10). It targets no app, so it has no `tell` block and no
    # Apple Event to bound by `with timeout`, and its text travels as an argument.
    "deploy.py:_alert": (
        "67d7b7038e43b4fb",
        "a `display alert` only: it targets no app",
    ),
    # The same alert for the wait on the daemon (#568). It ends by `giving up after`,
    # and the caller ends its child process when the wait is over.
    "deploy.py:_wait_notice": (
        "19edfc4f188a279b",
        "a `display alert` only: it targets no app",
    ),
    # The standard library's own script opens one URL in the default browser. No
    # script text of this package is in it.
    "deploy.py:dashboard": ("72151fc88ca66607", "webbrowser opens the dashboard URL"),
}


def _osascript_starts(source: str, rel: str) -> dict[str, str]:
    """``{"file:function": hash}`` for each function of ``source`` that starts
    osascript itself: it holds a string that matches ``_OSASCRIPT_START`` or one of
    ``_OSASCRIPT_NAMES``. The function is the outermost one (dotted for a method), and
    the hash covers its whole source, so a second script in a pinned function changes
    it. A start outside every function is ``file:<module>``.

    shortcut: a program name that is built at run time (``"osa" + "script"``), a shell
    line without an option (``osascript x.scpt``) and ``osacompile`` are not seen;
    widen the two patterns when the package gets such a call."""
    tree = ast.parse(source)
    found: dict[str, str] = {}

    def visit(node: ast.AST, prefix: str, owner: tuple[str, ast.AST] | None) -> None:
        if owner is None and isinstance(node, ast.ClassDef):
            prefix = f"{prefix}{node.name}."
        elif owner is None and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            owner = (f"{rel}:{prefix}{node.name}", node)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _OSASCRIPT_START.search(node.value)
        ) or getattr(node, "id", getattr(node, "attr", None)) in _OSASCRIPT_NAMES:
            key, scope = owner or (f"{rel}:<module>", None)
            text = ast.get_source_segment(source, scope) if scope else source
            found[key] = hashlib.sha256(text.encode()).hexdigest()[:16]
        for child in ast.iter_child_nodes(node):
            visit(child, prefix, owner)

    visit(tree, "", None)
    return found


def _package_osascript_starts() -> dict[str, str]:
    found: dict[str, str] = {}
    for path, _module in scripts.modules():
        rel = path.relative_to(_PACKAGE).as_posix()
        found |= _osascript_starts(path.read_text(), rel)
    return found


def test_every_call_site_template_is_in_the_compile_inventory():
    assert _outside_inventory(_CALL_SITES) == []
    # the check is not vacuous: a made-up script fails it, and so does an unresolved one
    made_up = _CallSite("x.py:1:_MADE_UP", "_MADE_UP", 30.0, 30.0, None, "on run\nend")
    unresolved = _CallSite("x.py:2:_GONE", "_GONE", None, None, "no attribute")
    assert _outside_inventory([made_up, unresolved, _CALL_SITES[0]]) == [
        "x.py:1:_MADE_UP",
        "x.py:2:_GONE",
    ]


def test_inline_scripts_start_only_at_the_door_or_in_a_pinned_function():
    found = _package_osascript_starts()
    assert _OSASCRIPT_DOOR in found
    outside = {key: digest for key, digest in found.items() if key != _OSASCRIPT_DOOR}
    pinned = {key: digest for key, (digest, _why) in _OSASCRIPT_PINNED.items()}
    assert outside == pinned, (
        "a function outside runtime.run_osascript starts osascript, or a pinned one "
        "changed. Send the script through run_osascript as a module-level constant, "
        f"or read the change and renew its entry in _OSASCRIPT_PINNED: {outside}"
    )
    # An entry names one function with its reason, never a whole module.
    for key, (_digest, why) in _OSASCRIPT_PINNED.items():
        file, _, name = key.partition(":")
        assert file.endswith(".py") and name.replace(".", "_").isidentifier(), key
        assert why
    # A change inside a pinned function changes its hash, and only its hash.
    deploy_source = (_PACKAGE / "deploy.py").read_text()
    assert deploy_source.count("as critical") == 1
    changed = _osascript_starts(
        deploy_source.replace("as critical", "as warning"), "deploy.py"
    )
    assert changed["deploy.py:_alert"] != pinned["deploy.py:_alert"]
    assert changed["deploy.py:_wait_notice"] == pinned["deploy.py:_wait_notice"]


@pytest.mark.parametrize(
    ("source", "key"),
    [
        # the abbreviation `tell app`, which the inventory's `tell application` misses
        (
            "def f():\n    run(['osascript', '-e', 'tell app \"Finder\" to quit'])\n",
            "f",
        ),
        ("def f():\n    run(['osascript', '-e', 'do shell script \"x\"'])\n", "f"),
        # JavaScript for Automation
        (
            "def f():\n    run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', s])\n",
            "f",
        ),
        # each piece is a part of an inventory script
        ("def f():\n    run(['osascript', '-e', 'on run', '-e', 'end run'])\n", "f"),
        ("def f():\n    os.system('osascript -e \"beep\"')\n", "f"),
        (
            "class C:\n  def m(self):\n    def g():\n      return 'osascript'\n",
            "C.m",
        ),
        ("def f():\n    return Foundation.NSAppleScript.alloc()\n", "f"),
        ("from webbrowser import MacOSXOSAScript as M\ndef f():\n    pass\n", None),
        ("def f():\n    return MacOSXOSAScript('default')\n", "f"),
        ("ARGV = ['osascript', '-e', SCRIPT]\n", "<module>"),
    ],
)
def test_the_inline_script_scan_finds_each_way_to_start_osascript(source, key):
    found = _osascript_starts(source, "x.py")
    assert list(found) == ([f"x.py:{key}"] if key else [])
    # `<module>` can never be pinned: the entry check wants a function name
    assert not any(k in _OSASCRIPT_PINNED for k in found)


def test_the_inline_script_scan_reads_the_package():
    # guard the scan itself: an empty one would make the check above vacuous
    files = [path for path, _module in scripts.modules()]
    assert len(files) >= 30, files
    assert {p.name for p in files} >= {"deploy.py", "runtime.py", "mail.py"}
    found = _package_osascript_starts()
    assert {_OSASCRIPT_DOOR, "deploy.py:_alert"} <= set(found)
    # a message that names osascript, and a docstring, start nothing
    quiet = 'X = "osascript failed: "\n\ndef f():\n    """Run osascript."""\n'
    assert _osascript_starts(quiet, "x.py") == {}
