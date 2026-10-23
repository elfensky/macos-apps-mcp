"""Second pass for contrast.py: candidate values and the preview-dim opacity."""
import importlib.util
import pathlib

here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("contrast", here / "contrast.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

P = c.parse
W, BG, SB, S2 = P("#fff"), P("#f5f5f7"), P("#e8e8ed"), P("#fbfbfd")
tint = lambda col, a, base: c.over(P(col)[:3] + (a,), base)  # noqa: E731
print("faint solved at 3:1 on surface/bg/sidebar:", c.solve(P("#aeaeb2"), [W, BG, SB], 3.0))
for name, col, a, bgs in (
    ("success", "#1e7133", 0.14, (W, BG, SB)),
    ("outbound", "#9026c6", 0.13, (W, BG, SB)),
    ("danger", "#c00a00", 0.12, (W, BG, SB)),
    ("orange", "#905600", 0.14, (W, BG, SB)),
):
    print(name, col, [round(c.ratio(P(col), tint(_tint, a, b)), 2) for b in bgs for _tint in [{"success":"#34c759","outbound":"#af52de","danger":"#ff3b30","orange":"#ff9f0a"}[name]]])
for col in ("#68686d", "#6e6e73", "#1d1d1f"):
    for o in (0.6, 0.7, 0.75, 0.8, 0.85):
        fg = c.over(P(col)[:3] + (o,), W)
        print(col, "opacity", o, round(c.ratio(fg, W), 2))
print("primary-hover #0066d6 on white:", round(c.ratio(P("#0066d6"), W), 2), "on selected row:", round(c.ratio(P("#0066d6"), tint("#007aff", .12, SB)), 2))
print("solve primary text 4.5 on surface+selected-row:", c.solve(P("#007aff"), [W, tint("#007aff", .12, SB)], 4.5))
print("white on #0066d6:", round(c.ratio(W, P("#0066d6")), 2))
print("dark: outbound solve:", c.solve(P("#bf5af2"), [c.over(P("#bf5af2")[:3]+(.13,), P("#2c2c2e")), c.over(P("#bf5af2")[:3]+(.13,), P("#262628"))], 4.5))

# .dim (preview card) with the proposed dark success on its tint: the whole subtree dims.
for o in (0.55, 0.7, 0.8, 0.85, 0.9):
    t = tint("#34c759", .14, W)
    fg = c.over(P("#1e7133")[:3] + (o,), W)  # text over page surface
    bg = c.over(t[:3] + (o,), W)             # tint also dims toward white
    print("dim", o, "success-dark on its tint", round(c.ratio(fg, bg), 2), "| text", round(c.ratio(c.over(P("#1d1d1f")[:3]+(o,), W), W), 2))
