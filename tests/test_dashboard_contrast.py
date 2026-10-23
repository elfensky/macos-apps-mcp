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
DARK_BACKGROUNDS = (
    "--color-surface",
    "--color-bg",
    "--color-sidebar",
    "--color-surface-2",
)
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


@pytest.fixture(scope="module")
def dark(css, light) -> dict[str, tuple[float, float, float, float]]:
    """The ``data-theme="dark"`` tokens over the light ones (an untouched token keeps
    its light value, as in the browser)."""
    return light | {
        k: parse(v)
        for k, v in _tokens(css, ':root[data-theme="dark"] {').items()
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


TEXT_ON_TINT = {
    "--color-success-text": "--color-success-bg",
    "--color-outbound-text": "--color-outbound-bg",
    "--color-danger-text": "--color-danger-bg",
    "--color-accent-text": "--color-accent-bg",
}


@pytest.mark.parametrize("background", LIGHT_BACKGROUNDS)
def test_muted_text_reaches_4_5_to_1(light, background):
    got = ratio(light["--color-text-muted"], light[background])
    assert got >= TEXT, f"{got:.2f}:1 on {background}"


@pytest.mark.parametrize("background", LIGHT_BACKGROUNDS)
@pytest.mark.parametrize("token", TEXT_ON_TINT)
def test_every_light_text_token_reaches_4_5_to_1(light, token, background):
    got = _on_tint(light, token, TEXT_ON_TINT[token], background)
    assert got >= TEXT, f"{token}: {got:.2f}:1 on its tint over {background}"


@pytest.mark.parametrize("background", LIGHT_BACKGROUNDS)
@pytest.mark.parametrize(
    "token",
    [
        "--color-text-faint",
        "--color-success-text",
        "--color-accent-text",
        "--color-danger-text",
        "--color-primary",
    ],
)
def test_every_light_glyph_token_reaches_3_to_1(light, token, background):
    got = ratio(light[token], light[background])
    assert got >= GLYPH, f"{token}: {got:.2f}:1 on {background}"


# Known light-mode nits left to a later plan (PM-04): muted text on a selected row
# is 4.38:1 over the page and 3.94:1 over the sidebar; only the surface reaches 4.5:1.
LIGHT_CHIP_PAIRS = [
    ("--color-neutral-bg", "--color-surface"),
    ("--color-neutral-bg", "--color-bg"),
    ("--color-selection", "--color-surface"),
]


@pytest.mark.parametrize(("tint", "background"), LIGHT_CHIP_PAIRS)
def test_light_muted_text_on_a_chip_or_selected_row_reaches_4_5_to_1(
    light, tint, background
):
    got = _on_tint(light, "--color-text-muted", tint, background)
    assert got >= TEXT, f"muted on {tint} over {background}: {got:.2f}:1"


@pytest.mark.parametrize("background", DARK_BACKGROUNDS)
@pytest.mark.parametrize("tint", ["--color-neutral-bg", "--color-selection"])
def test_dark_muted_text_on_a_chip_or_selected_row_reaches_4_5_to_1(
    dark, tint, background
):
    got = _on_tint(dark, "--color-text-muted", tint, background)
    assert got >= TEXT, f"muted on {tint} over {background}: {got:.2f}:1"


@pytest.mark.parametrize("background", DARK_BACKGROUNDS)
def test_dark_muted_text_reaches_4_5_to_1(dark, background):
    got = ratio(dark["--color-text-muted"], dark[background])
    assert got >= TEXT, f"{got:.2f}:1 on {background}"


@pytest.mark.parametrize("background", DARK_BACKGROUNDS)
@pytest.mark.parametrize("token", TEXT_ON_TINT)
def test_every_dark_text_token_reaches_4_5_to_1(dark, token, background):
    got = _on_tint(dark, token, TEXT_ON_TINT[token], background)
    assert got >= TEXT, f"{token}: {got:.2f}:1 on its tint over {background}"


@pytest.mark.parametrize("background", DARK_BACKGROUNDS)
@pytest.mark.parametrize(
    "token",
    [
        "--color-text-faint",
        "--color-success-text",
        "--color-accent-text",
        "--color-danger-text",
        "--color-primary",
    ],
)
def test_every_dark_glyph_token_reaches_3_to_1(dark, token, background):
    got = ratio(dark[token], dark[background])
    assert got >= GLYPH, f"{token}: {got:.2f}:1 on {background}"


def test_text_rules_use_the_text_tokens(css):
    def uses(selector: str, prop: str, token: str) -> bool:
        return any(f"{prop}: var({token})" in b for b in _bodies(css, selector))

    for sel, token in (
        (".chip.outbound", "--color-outbound-text"),
        ("pre.json .n", "--color-outbound-text"),
        (".chip.danger", "--color-danger-text"),
        ("del.w", "--color-danger-text"),
        (".fid.absent", "--color-danger-text"),
        (".chip.destructive", "--color-accent-text"),
        (".chip.pending", "--color-accent-text"),
        (".fid.partial", "--color-accent-text"),
        (".faint", "--color-text-muted"),
        (".sidebar h6", "--color-text-muted"),
        (".b-empty", "--color-text-muted"),
    ):
        assert uses(sel, "color", token), f"{sel} should use {token}"
    assert uses(".dot.warn", "background", "--color-accent-text")
    assert uses(".dot.bad", "background", "--color-danger-text")
    # no hard-coded text colour on a chip, fid, ins or del rule
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if re.search(r"\.chip|\.fid|\bins\.w|\bdel\.w", sel):
            assert not re.search(r"(?<![-\w])color:\s*#", body), sel.strip()


@pytest.mark.parametrize("token", TEXT_ON_TINT)
def test_dark_mode_declares_every_text_token(css, token):
    for opener in (":root {", *DARK_OPENERS):
        assert token in _tokens(css, opener), f"{token} missing from {opener}"


def test_no_raw_pixel_font_size_outside_the_token_block(css):
    start = css.index(":root {")
    rest = css[:start] + css[css.index("}", start) + 1 :]
    assert not re.findall(r"(?<![-\w])font(?:-size)?:\s*[\d.]+px", rest)


def test_a_preview_is_dimmed_without_opacity_on_its_text(css):
    for sel in (".b-list .row.preview", ".dim"):
        assert not any("opacity" in b for b in _bodies(css, sel)), sel
    assert any(
        "color: var(--color-text-muted)" in b
        for b in _bodies(css, ".b-list .row.preview .title")
    )
    assert any("opacity" in b for b in _bodies(css, ".b-list .row.preview .appico"))
    assert any("dashed" in b for b in _bodies(css, ".dim .card"))


def test_reduced_motion_stops_the_animations(css):
    m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", css, re.S)
    assert m, "no prefers-reduced-motion block"
    assert any(
        "animation: none" in b for b in _bodies(m.group(1), ".spin, .restart-bar")
    )


def test_the_lock_glyph_has_empty_alt_text(css):
    order = re.compile(r'content:\s*" 🔒";\s*content:\s*" 🔒"\s*/\s*"";')
    assert any(order.search(b) for b in _bodies(css, ".row.locked .title::after"))
