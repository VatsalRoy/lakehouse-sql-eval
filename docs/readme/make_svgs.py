"""Render the README panels as SVGs in the evaluation-console style.

GitHub strips CSS from README files but displays SVG images, so each section of the
console is drawn as one image. Numbers are the final Llama 3.3 70B results.
Run:  python docs/readme/make_svgs.py
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent
W = 960
SANS = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
DISP = "'Space Grotesk', Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

BG, CARD, BORDER, LINE = "#0b0d10", "#12151a", "#1f242c", "#1d2128"
TEXT, STRONG, MUTED, FAINT = "#e7e9ec", "#f3f4f6", "#9aa3ae", "#7c8592"
GREEN, RED = "#34d399", "#ff7b72"
COND = [("A", "raw schema", "#8b95a5"), ("B", "+ column comments", "#c9d1dc"),
        ("C", "metric view", "#34d399"), ("C−", "metric view, no synonyms", "#1f8f68")]


def t(x, y, s, size=13, color=TEXT, font=SANS, weight=400, anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}" {extra}>{escape(s)}</text>')


def rect(x, y, w, h, fill, r=0, stroke=None, extra=""):
    s = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{s} {extra}/>'


def wrap(s, size, width, mono=False):
    per = width / (size * (0.6 if mono else 0.54))
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > per:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur]


def svg(name, h, body, title):
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}" '
           f'role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>'
           f'{rect(0, 0, W, h, BG, 16)}{"".join(body)}</svg>')
    (OUT / name).write_text(doc, encoding="utf-8")


def card(x, y, w, h):
    return rect(x + 0.5, y + 0.5, w - 1, h - 1, CARD, 16, BORDER)


def dot(x, y, color, r=4.5):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'


def key(x, y, k, color):
    return dot(x + 4.5, y - 4.5, color) + t(x + 15, y, k, 13, STRONG, MONO, 600)


# ----------------------------------------------------------------------------- 1. hero
def hero():
    b = [rect(0, 0, W, 56, "#0e1014", 16), rect(0, 40, W, 16, "#0e1014"),
         rect(0, 56, W, 1, LINE),
         '<g transform="translate(24,17)"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" '
         f'stroke="{GREEN}" stroke-width="2"/><path d="M8 15l3-4 2 2 3-5" fill="none" stroke="{GREEN}" '
         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>',
         t(56, 34, "lakehouse-sql-eval", 16, STRONG, DISP, 600),
         rect(552, 16, 152, 26, "#0f2a20", 13, "#14532d"), dot(567, 29, GREEN, 3.5),
         t(578, 33, "Final eval · Nov 2026", 12, "#6ee7b7"),
         t(936, 33, "llama-3.3-70b · 720 generations", 12, MUTED, MONO, anchor="end"),
         t(24, 96, "60 business questions × 3 runs × 4 grounding conditions", 12, FAINT, MONO),
         t(24, 140, "A semantic layer nearly doubled how often", 34, STRONG, DISP, 600, extra='letter-spacing="-0.8"'),
         t(24, 180, "the AI got the number right", 34, STRONG, DISP, 600, extra='letter-spacing="-0.8"')]
    y = 214
    b += [rect(24.5, y + .5, 150, 104, CARD, 14, "#222731"), t(44, y + 28, "Raw schema", 12, MUTED),
          t(42, y + 86, "46", 54, MUTED, MONO, 600, extra='letter-spacing="-2"'),
          t(106, y + 86, "%", 28, MUTED, MONO, 600),
          f'<path d="M188 {y+52}h28M208 {y+45}l8 7-8 7" fill="none" stroke="{GREEN}" stroke-width="2.5" '
          'stroke-linecap="round" stroke-linejoin="round"/>',
          rect(230.5, y + .5, 150, 104, "#0f2a20", 14, "#1d5c43"), t(250, y + 28, "With metric view", 12, "#6ee7b7"),
          t(248, y + 86, "82", 54, GREEN, MONO, 600, extra='letter-spacing="-2"'),
          t(312, y + 86, "%", 28, GREEN, MONO, 600),
          t(400, y + 48, "+36 pts", 22, GREEN, MONO, 600),
          t(400, y + 72, "95% CI +22 to +51", 12, MUTED), t(400, y + 90, "significant (paired bootstrap)", 12, MUTED)]
    return b


def hero_svg():
    b = hero()
    # callouts sit to the right of the tiles, aligned with the tile row
    blocks = [
        (214, "84%", "of raw-schema failures were silent: the query ran and returned a believable wrong number",
         "#1f1214", "#4a1d20", RED, "#e4c9c7"),
        (288, "+3", "pts from column comments alone, not significant. Describing data does not teach business rules",
         CARD, "#222731", TEXT, "#b9c0ca")]
    for yy, num, s, fill, stroke, ncol, tcol in blocks:
        lines = wrap(s, 12.5, 230)
        b += [rect(600.5, yy + .5, 335, 66, fill, 12, stroke), t(616, yy + 42, num, 24, ncol, MONO, 600)]
        for j, ln in enumerate(lines[:3]):
            b.append(t(692, yy + 22 + j * 17, ln, 12.5, tcol))
    svg("hero.svg", 374, b, "Raw schema 46% accuracy versus 82% with a metric view; 84% of raw-schema failures were silent")


# ----------------------------------------------------------------------------- 2. categories
def categories_svg():
    b = [card(0, 0, W, 440), t(28, 42, "Where the semantic layer helps, and where it doesn't", 20, STRONG, DISP, 600),
         t(28, 66, "Accuracy per question category. The bar runs from raw schema (A) to metric view (C).", 13, MUTED)]
    x = 28
    for k, label, color in COND:
        w = 40 + len(k) * 8 + len(label) * 7.3
        b += [rect(x + .5, 84.5, w, 28, BG, 14, "#222731"), dot(x + 16, 98.5, color),
              t(x + 27, 103, k, 13, STRONG, MONO, 600), t(x + 33 + len(k) * 8, 103, label, 13, "#c9cfd6")]
        x += w + 8
    X0, X1 = 228, 820
    sx = lambda v: X0 + (X1 - X0) * v / 100
    for v in (0, 25, 50, 75, 100):
        b.append(t(sx(v), 144, f"{v}%" if v == 100 else str(v), 11, "#6b7480", MONO,
                   anchor="start" if v == 0 else "end" if v == 100 else "middle"))
    b.append(t(932, 144, "C vs A", 11, "#6b7480", MONO, anchor="end"))
    rows = [("Lookup", "Find a value, no rules", [100, 100, 100, 100], "0"),
            ("Aggregation", "Counts and sums of records", [71, 80, 56, 62], "−16"),
            ("Business definition", "Revenue, AOV, refund rate", [9, 13, 100, 78], "+91"),
            ("Time / fiscal", "Fiscal quarters and years", [2, 0, 71, 29], "+69")]
    for i, (name, note, vals, delta) in enumerate(rows):
        y = 156 + i * 62
        cy = y + 31
        b += [rect(28, y, W - 56, 1, LINE), t(28, cy - 3, name, 14, STRONG, weight=600), t(28, cy + 15, note, 12, FAINT),
              rect(X0, cy - 1, X1 - X0, 2, BORDER)]
        for v in (25, 50, 75):
            b.append(f'<line x1="{sx(v)}" y1="{cy-9}" x2="{sx(v)}" y2="{cy+9}" stroke="#232933" stroke-dasharray="3 3"/>')
        a, c = vals[0], vals[2]
        lo, hi = min(a, c), max(a, c)
        if hi > lo:
            b.append(rect(sx(lo), cy - 3, sx(hi) - sx(lo), 6, "rgba(52,211,153,0.45)" if c > a else "rgba(255,123,114,0.5)", 3))
        seen = {}
        for j in (0, 1, 3, 2):  # draw C last so it sits on top
            v = vals[j]
            n = seen.get(v, 0)
            seen[v] = n + 1
            r = 7 if j == 2 else 5.5
            b.append(f'<circle cx="{sx(v)}" cy="{cy}" r="{r}" fill="{COND[j][2]}" stroke="{CARD}" stroke-width="2.5"/>')
        pos = delta.startswith("+")
        neg = delta.startswith("−")
        bg, col = ("#0f2a20", GREEN) if pos else ("#2a1316", RED) if neg else ("#1a1e25", MUTED)
        b += [rect(932 - 58, cy - 14, 58, 28, bg, 8), t(932 - 29, cy + 5, delta, 14, col, MONO, 600, "middle")]
    b.append(t(28, 420, "Lookup: all four conditions at 100%. Aggregation drop is not significant (95% CI −47 to +13).", 12, FAINT))
    svg("categories.svg", 440, b, "Accuracy by category for conditions A, B, C and C minus")


# ----------------------------------------------------------------------------- 3. examples
def examples_svg():
    ex = [("B02", "A", "What were our total sales in FY2025?", "$9.27M", "$7.32M",
           "Refunds were never subtracted and internal test accounts were counted. Too high, and nothing looked broken."),
          ("B01", "B", "What was total net revenue in FY2025?", "$132K", "$7.32M",
           "SUM(order − refund) made every order without a refund NULL, so most of the revenue silently disappeared."),
          ("B08", "B", "What was the refund rate in FY2025?", "82.0%", "6.8%",
           "Divided refunds by refunded orders only, and dated them by refund instead of order.")]
    b = [t(24, 34, "What the business user would have seen", 20, STRONG, DISP, 600)]
    cw, gap, y0, ch = 296, 12, 54, 262
    for i, (qid, cond, q, model, truth, why) in enumerate(ex):
        x = 24 + i * (cw + gap)
        b += [card(x, y0, cw, ch), t(x + 18, y0 + 30, f"{qid} · condition {cond}", 12, FAINT, MONO),
              rect(x + cw - 128.5, y0 + 14.5, 112, 24, "#2a1316", 12, "#4a1d20"),
              t(x + cw - 72, y0 + 31, "Ran fine · wrong", 11, "#ff9b93", weight=600, anchor="middle")]
        for j, ln in enumerate(wrap(f"“{q}”", 15, cw - 36)):
            b.append(t(x + 18, y0 + 62 + j * 21, ln, 15, STRONG, weight=500))
        sy = y0 + 98
        half = cw / 2
        b += [rect(x + 1, sy, half - 1, 72, "#170f11"), rect(x + half, sy, half - 1, 72, "#0d1a15"),
              rect(x + 1, sy, cw - 2, 1, BORDER), rect(x + 1, sy + 72, cw - 2, 1, BORDER), rect(x + half, sy, 1, 72, BORDER),
              t(x + 18, sy + 24, "AI ANSWERED", 10.5, "#c99a96", extra='letter-spacing="0.8"'),
              t(x + 18, sy + 56, model, 24, RED, MONO, 600),
              rect(x + 18, sy + 47, len(model) * 14.4, 2, RED),
              t(x + half + 18, sy + 24, "CORRECT", 10.5, "#8fd9b9", extra='letter-spacing="0.8"'),
              t(x + half + 18, sy + 56, truth, 24, GREEN, MONO, 600)]
        for j, ln in enumerate(wrap(why, 12.5, cw - 36)):
            b.append(t(x + 18, sy + 98 + j * 19, ln, 12.5, "#b9c0ca"))
    svg("examples.svg", y0 + ch + 20, b, "Three silent wrong answers: $9.27M vs $7.32M, $132K vs $7.32M, 82.0% vs 6.8%")


# ----------------------------------------------------------------------------- 4. outcomes + reasons
def outcomes_svg():
    H = 392
    cw = 444
    b = [card(24, 0, cw, H), t(50, 40, "Outcome of every generated query", 17, STRONG, DISP, 600),
         t(50, 62, "The red share is what makes raw-schema SQL dangerous", 13, MUTED)]
    data = [(82, 82, 16), (87, 81, 12), (147, 14, 19), (121, 19, 40)]  # of 180
    bx0, bx1 = 108, 24 + cw - 26
    for i, ((k, _, color), (c, s, e)) in enumerate(zip(COND, data)):
        y = 92 + i * 56
        b.append(key(50, y + 20, k, color))
        span = bx1 - bx0 - 6
        x = bx0
        for n, fill, col, minw in [(c, "#232a33", "#d5dae0", 90), (s, "#e5484d", "#ffffff", 74), (e, "#4a2427", "#ffb4ab", 30)]:
            val = round(100 * n / 180)
            label = f"{val}% " + ("correct" if fill == "#232a33" else "silent") if fill != "#4a2427" else f"{val}%"
            w = span * n / 180
            b.append(rect(x, y, w, 30, fill, 6))
            if w >= minw:
                b.append(t(x + 9, y + 20, label, 12, col, weight=600))
            elif w >= 21:
                b.append(t(x + 6, y + 20, f"{val}%", 12, col, weight=600))
            x += w + 3
    ly = 92 + 4 * 56 + 20
    for j, (fill, lab) in enumerate([("#232a33", "Correct"), ("#e5484d", "Silent wrong"), ("#4a2427", "Error or empty (visible)")]):
        lx = [92, 180, 296][j]
        b += [rect(lx, ly - 10, 10, 10, fill, 3, "#3a424d" if j == 0 else None), t(lx + 16, ly, lab, 12, MUTED)]
    b.append(t(50, H - 26, "% of 180 generations per condition", 11, FAINT, MONO))

    x0 = 24 + cw + 24
    b += [card(x0, 0, cw, H), t(x0 + 26, 40, "Top reason each condition failed", 17, STRONG, DISP, 600),
          t(x0 + 26, 62, "Share of that condition's failed generations", 13, MUTED)]
    reasons = [[("Wrong business definition", 46), ("Fan-out join", 18), ("Runtime error", 14)],
               [("Wrong business definition", 57), ("Runtime error", 13), ("NULL arithmetic", 11)],
               [("Runtime error", 58), ("Over-applied definition", 24), ("Unit or scale", 9)],
               [("Runtime error", 68), ("Over-applied definition", 15), ("Extra filter", 8)]]
    for i, ((k, _, color), items) in enumerate(zip(COND, reasons)):
        y = 82 + i * 76
        b += [rect(x0 + 26, y, cw - 52, 1, LINE), key(x0 + 26, y + 24, k, color)]
        for j, (name, pct) in enumerate(items):
            yy = y + 24 + j * 20
            bx, bw = x0 + 252, cw - 252 - 70
            b += [t(x0 + 76, yy, name, 12.5, "#d5dae0"), rect(bx, yy - 8, bw, 8, "#1b2027", 4),
                  rect(bx, yy - 8, bw * pct / 100, 8, "#8b95a5", 4),
                  t(x0 + cw - 26, yy, f"{pct}%", 12, TEXT, MONO, 600, "end")]
    svg("outcomes.svg", H, b, "Outcome shares and top failure reasons for each condition")


# ----------------------------------------------------------------------------- 5. judge / synonyms / cost
def insights_svg():
    cw, gap, H = 296, 12, 318
    panels = [
        ("Can an LLM judge catch these?", "Wrong answers the judge approved",
         [20, 25, 42, 64], "bar_red",
         "It trusted wrong answers that used the metric view twice as often. Score by execution, not by judge.", RED),
        ("Do synonyms matter?", "Questions using everyday words like “sales”",
         [10, 20, 97, 57], "bar_cond",
         "Removing synonyms and descriptions cost 40 pts on everyday wording.", GREEN),
        ("What it costs", "Prompt tokens per question vs. accuracy",
         [("515", "46%"), ("1,285", "48%"), ("2,715", "82%"), ("1,498", "67%")], "table",
         "C sends 5× the tokens: 3,325 per correct answer vs 1,130 for A.", "#8b95a5")]
    b = []
    for i, (title, sub, vals, kind, note, ncol) in enumerate(panels):
        x = 24 + i * (cw + gap)
        b += [card(x, 0, cw, H), t(x + 22, 38, title, 16.5, STRONG, DISP, 600), t(x + 22, 60, sub, 12.5, MUTED)]
        for j, ((k, _, color), v) in enumerate(zip(COND, vals)):
            y = 92 + j * 34
            b.append(key(x + 22, y + 5, k, color))
            if kind == "table":
                b += [rect(x + 22, y - 16, cw - 44, 1, LINE), t(x + 78, y + 5, f"{v[0]} tok", 13, "#b9c0ca", MONO),
                      t(x + cw - 22, y + 5, v[1], 13, TEXT, MONO, 600, "end")]
            else:
                bx, bw = x + 72, cw - 72 - 66
                b += [rect(bx, y - 6, bw, 12, "#1b2027", 6),
                      rect(bx, y - 6, bw * v / 100, 12, RED if kind == "bar_red" else color, 6),
                      t(x + cw - 22, y + 5, f"{v}%", 13, TEXT, MONO, 600, "end")]
        lines = wrap(note, 12.5, cw - 60)
        ny = 92 + 4 * 34 + 8
        b.append(rect(x + 22, ny, 2, len(lines) * 19 + 4, ncol))
        for j, ln in enumerate(lines):
            b.append(t(x + 34, ny + 16 + j * 19, ln, 12.5, "#c9cfd6"))
    svg("insights.svg", H, b, "LLM judge approval of wrong answers, synonym accuracy, and token cost per condition")


# ----------------------------------------------------------------------------- 6. architecture
def architecture_svg():
    rows = [("1 · BUILD THE LAKEHOUSE", [("UC Volume", "synthetic retail files"), ("Lakeflow pipeline", "bronze → silver → gold"),
                                         ("Unity Catalog gold", "star schema + checks"), ("Metric views", "governed metric definitions")]),
            ("2 · EVALUATE", [("Prompts A / B / C / C−", "only the context differs"), ("ai_query", "Llama 3.3 70B · 720 runs"),
                              ("Execute + score", "answer key ±0.5% + judge"), ("MLflow 3 + eval.*", "genai.evaluate + Delta")]),
            ("3 · SERVE AND GUARD", [("Databricks App", "this evaluation console"), ("Nightly regression gate", "fails + emails on a drop"),
                                     ("One bundle", "databricks bundle deploy")])]
    nw, gap = 210, 24
    b = [t(24, 36, "How it fits together", 20, STRONG, DISP, 600)]
    for r, (label, nodes) in enumerate(rows):
        y = 64 + r * 118
        b.append(t(24, y + 12, label, 11, FAINT, MONO, extra='letter-spacing="0.6"'))
        for i, (name, sub) in enumerate(nodes):
            x = 24 + i * (nw + gap)
            green = name.startswith(("Metric", "Databricks App"))
            b += [rect(x + .5, y + 26.5, nw - 1, 66, "#0f2a20" if green else CARD, 12, "#1d5c43" if green else "#222731"),
                  t(x + 16, y + 54, name, 14, GREEN if green else STRONG, weight=600),
                  t(x + 16, y + 76, sub, 11.5, MUTED, MONO)]
            if i < len(nodes) - 1:
                ax = x + nw + 4
                b.append(f'<path d="M{ax} {y+59}h{gap-8}M{ax+gap-14} {y+53}l6 6-6 6" fill="none" stroke="{GREEN}" '
                         'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    svg("architecture.svg", 64 + 3 * 118 - 8, b, "Architecture: lakehouse build, evaluation, and serving")


if __name__ == "__main__":
    hero_svg(); categories_svg(); examples_svg(); outcomes_svg(); insights_svg(); architecture_svg()
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))