"""WCAG 2.x contrast of the dashboard colour tokens (#428, FIX-12).

Reads the real token values from macos_apps_mcp/dashboard/dashboard.css (the light
``:root`` block and the ``:root[data-theme="dark"]`` block), composites every rgba
over its background, and prints the ratio for each pair the Phase 5 UI review names.
With ``--solve`` it also searches, per failing text colour, the lightest same-hue
(HSL) replacement that reaches the target on every background it sits on.

Run: uv run python .planning/phases/05.1-.../05.1-proto/contrast.py [--solve]
Stdlib only. Not part of the package, not collected by pytest, excluded from ruff.
"""

from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parents[4] / "macos_apps_mcp/dashboard/dashboard.css"
TEXT, UI = 4.5, 3.0


def _block(css: str, opener: str) -> dict[str, str]:
    start = css.index(opener) + len(opener)
    end = css.index("}", start)
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", css[start:end]))


def parse(v: str) -> tuple[float, float, float, float]:
    v = v.strip()
    if v.startswith("#"):
        v = v[1:]
        v = "".join(c * 2 for c in v) if len(v) == 3 else v
        r, g, b = (int(v[i : i + 2], 16) for i in (0, 2, 4))
        return r, g, b, 1.0
    m = re.match(r"rgba?\(([^)]+)\)", v)
    parts = [float(x) for x in m.group(1).split(",")]
    return parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else 1.0


def over(fg, bg):
    """Composite fg (r, g, b, a) over an opaque bg (r, g, b, 1)."""
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def lum(c) -> float:
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def ratio(a, b) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hexof(c) -> str:
    return "#%02x%02x%02x" % tuple(round(x) for x in c[:3])


def solve(color, bgs, target):
    """Lightest same-hue/saturation colour (HSL lightness lowered, or raised in dark)
    that reaches ``target`` on every bg. Returns hex or None."""
    r, g, b = (x / 255 for x in color[:3])
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    dark_bg = lum(bgs[0]) < 0.2
    steps = [i / 1000 for i in range(1001)]
    for lv in sorted(steps, key=lambda x: abs(x - l)):
        if (lv > l) == dark_bg or lv == l:
            rgb = tuple(round(x * 255) for x in colorsys.hls_to_rgb(h, lv, s))
            c = rgb + (1.0,)
            if all(ratio(c, bg) >= target for bg in bgs):
                return hexof(c)
    return None


def main() -> None:
    css = CSS.read_text()
    light = _block(css, ":root {")
    dark = {**light, **_block(css, ':root[data-theme="dark"] {')}
    for mode, tok in (("LIGHT", light), ("DARK", dark)):
        t = {k: parse(v) for k, v in tok.items() if k.startswith("--color")}
        surface, bgc, side = t["--color-surface"], t["--color-bg"], t["--color-sidebar"]
        orange = parse("#c77700") if mode == "LIGHT" else t["--color-accent"]
        sjson = parse("#b3541e") if mode == "LIGHT" else parse("#ff9f6b")
        tint = lambda name, base=surface: over(t[name], base)  # noqa: E731
        rows = [
            # (label, fg, bg, target)
            ("faint on surface (.faint, empty state on card)", t["--color-text-faint"], surface, TEXT),
            ("faint on page bg (.b-empty, b-detail)", t["--color-text-faint"], bgc, TEXT),
            ("faint on sidebar (sidebar h6)", t["--color-text-faint"], side, TEXT),
            ("muted on surface", t["--color-text-muted"], surface, TEXT),
            ("muted on page bg", t["--color-text-muted"], bgc, TEXT),
            ("muted on sidebar (.count, .sidebar-foot)", t["--color-text-muted"], side, TEXT),
            ("muted on .preview row (opacity .6 over surface)", over(t["--color-text-muted"][:3] + (0.6,), surface), surface, TEXT),
            ("text on .preview row (opacity .6 over surface)", over(t["--color-text"][:3] + (0.6,), surface), surface, TEXT),
            ("chip.additive/.ok + ins.w: success on 14% tint (surface)", t["--color-success"], tint("--color-success-bg"), TEXT),
            ("chip.outbound: outbound on 13% tint (surface)", t["--color-outbound"], tint("--color-outbound-bg"), TEXT),
            ("chip.destructive/.pending/.fid.partial: orange on 14% tint", orange, tint("--color-accent-bg"), TEXT),
            ("chip.danger / del.w: danger on 12% tint", t["--color-danger"], tint("--color-danger-bg"), TEXT),
            ("link/primary text on surface", t["--color-primary"], surface, TEXT),
            ("primary text on selected nav row (12% tint on sidebar)", t["--color-primary"], tint("--color-selection", side), TEXT),
            ("white on .btn.primary", (255, 255, 255, 1.0), t["--color-primary"], TEXT),
            ("pre.json .s string colour on surface-2", sjson, t["--color-surface-2"], TEXT),
            ("pre.json .n outbound on surface-2", t["--color-outbound"], t["--color-surface-2"], TEXT),
            ("focus ring today: selection 3px over surface", tint("--color-selection"), surface, UI),
            ("focus ring proposed: primary over surface", t["--color-primary"], surface, UI),
            ("focus ring proposed: primary over sidebar", t["--color-primary"], side, UI),
            ("dot.ok success on surface (glyph)", t["--color-success"], surface, UI),
            ("dot default faint on surface (glyph)", t["--color-text-faint"], surface, UI),
            ("switch off track (5% neutral) vs surface (glyph)", tint("--color-neutral-bg"), surface, UI),
            ("switch on track primary vs surface (glyph)", t["--color-primary"], surface, UI),
        ]
        print(f"\n== {mode} ==")
        print(f"{'ratio':>6}  {'need':>4}  verdict  pair  (fg on bg)")
        for label, fg, bg, need in rows:
            r = ratio(fg, bg)
            print(f"{r:6.2f}  {need:4.1f}  {'ok  ' if r >= need else 'FAIL'}  {label}  ({hexof(fg)} on {hexof(bg)})")
        if "--solve" in sys.argv and mode == "LIGHT":
            print("\n-- proposals (lightest same-hue colour reaching the target) --")
            bgs_faint = [surface, bgc, side]
            print("faint -> text 4.5 on surface, bg, sidebar:", solve(t["--color-text-faint"], bgs_faint, TEXT))
            print("muted -> 4.5 on surface, bg, sidebar:", solve(t["--color-text-muted"], bgs_faint, TEXT))
            print("muted on preview (0.6 opacity) -> need base:", solve(t["--color-text-muted"], bgs_faint, TEXT))
            for name, key, tn in (
                ("success text", "--color-success", "--color-success-bg"),
                ("outbound text", "--color-outbound", "--color-outbound-bg"),
                ("danger text", "--color-danger", "--color-danger-bg"),
            ):
                bgs = [tint(tn), tint(tn, bgc), tint(tn, side)]
                print(f"{name}: -> 4.5 on its tint over surface/bg/sidebar:", solve(t[key], bgs, TEXT))
            bgs = [tint("--color-accent-bg"), tint("--color-accent-bg", bgc), tint("--color-accent-bg", side)]
            print("orange text:", solve(parse("#c77700"), bgs, TEXT))
            print("pre.json .s #b3541e on surface-2:", solve(parse("#b3541e"), [t["--color-surface-2"]], TEXT))


if __name__ == "__main__":
    main()
