"""#56 acceptance: every osascript template carries a balanced `with timeout`.

Introspective (not a hardcoded list) so a NEW template added later with a `tell
application` block but no `with timeout` fails this test — the guard can't rot.
"""

from __future__ import annotations

import importlib
import pkgutil

import mac_mcp.adapters as adapters_pkg


def _osascript_templates():
    """(label, source) for each module-level string that drives an app via osascript."""
    for mod_info in pkgutil.iter_modules(adapters_pkg.__path__):
        mod = importlib.import_module(f"mac_mcp.adapters.{mod_info.name}")
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
