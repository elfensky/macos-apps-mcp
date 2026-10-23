"""Measured contrast and the stylesheet pins of the dashboard (#428, FIX-12).

Every test reads the stylesheet the dashboard serves (``/static/dashboard.css``), so a
value edited in the file is the value measured here. The maths (parse, composite,
luminance, ratio) is copied from ``.planning/.../05.1-proto/contrast.py``: that folder
is outside the package and outside ``testpaths``, so it cannot be imported.
"""

from __future__ import annotations

import re

import pytest

from tests._dashboard import get

TEXT, GLYPH = 4.5, 3.0
LIGHT_BACKGROUNDS = ("--color-surface", "--color-bg", "--color-sidebar")
DARK_OPENERS = (':root:not([data-theme="light"]) {', ':root[data-theme="dark"] {')


def _css() -> str:
    """The served stylesheet, comments stripped."""
    r = get("/static/dashboard.css")
    assert r.status_code == 200
    return re.sub(r"/\*.*?\*/", "", r.text, flags=re.S)


def _tokens(css: str, opener: str) -> dict[str, str]:
    start = css.index(opener) + len(opener)
    return dict(
        re.findall(r"(--[\w-]+):\s*([^;]+);", css[start : css.index("}", start)])
    )


def _bodies(css: str, selector: str) -> list[str]:
    """Declaration bodies of every rule whose whole selector text is ``selector``
    (rules nested in an ``@media`` block included)."""
    return [
        body
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if " ".join(sel.split()) == selector
    ]


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


@pytest.fixture(scope="module")
def css() -> str:
    return _css()


@pytest.fixture(scope="module")
def light(css) -> dict[str, tuple[float, float, float, float]]:
    return {
        k: parse(v)
        for k, v in _tokens(css, ":root {").items()
        if k.startswith("--color")
    }


def _on_tint(light, fg: str, tint: str, background: str) -> float:
    """Ratio of ``fg`` on its translucent ``tint`` composited over ``background``."""
    return ratio(light[fg], over(light[tint], light[background]))


@pytest.mark.parametrize("background", LIGHT_BACKGROUNDS)
def test_the_adds_chip_and_word_diff_reach_4_5_to_1(css, light, background):
    got = _on_tint(light, "--color-success-text", "--color-success-bg", background)
    assert got >= TEXT, f"{got:.2f}:1 on {background}"
    for sel in (".chip.additive", ".chip.ok", "ins.w"):
        assert any(
            "color: var(--color-success-text)" in b for b in _bodies(css, sel)
        ), sel
    assert any(
        "background: var(--color-success-text)" in b for b in _bodies(css, ".dot.ok")
    )


def test_the_focus_ring_is_a_solid_primary_outline(css, light):
    ring = "outline: 2px solid var(--color-primary)"
    for sel in (":focus-visible", "button.switch:focus-visible"):
        assert any(ring in b for b in _bodies(css, sel)), sel
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for decl in re.findall(r"outline[^;]*", body):
            assert "--color-selection" not in decl, sel.strip()
    for background in LIGHT_BACKGROUNDS:
        assert ratio(light["--color-primary"], light[background]) >= GLYPH, background
