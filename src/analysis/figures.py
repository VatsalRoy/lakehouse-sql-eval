"""Report figures (matplotlib). Pure functions: DataFrame in -> PNG out.

Colour rules: one fixed colour per condition (never re-ordered), status colours only for outcomes,
a single blue ramp for counts, values printed on marks so colour never carries meaning alone.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

CONDITIONS = ["A_raw", "B_comments", "C_metric_view", "C_nosyn"]
NAMES = {"A_raw": "A: raw schema", "B_comments": "B: + column comments",
         "C_metric_view": "C: metric view", "C_nosyn": "C−: metric view, no synonyms"}
COLORS = {"A_raw": "#2a78d6", "B_comments": "#eb6834", "C_metric_view": "#1baf7a", "C_nosyn": "#eda100"}
STATUS = {"correct": "#0ca30c", "silent_wrong": "#d03b3b", "empty": "#fab219", "error": "#ec835a"}
STATUS_NAMES = {"correct": "Correct", "silent_wrong": "Silent wrong (ran, wrong number)",
                "empty": "Empty result", "error": "Error"}
CATEGORIES = ["ALL", "lookup", "aggregation", "business_definition", "time_fiscal"]
CAT_NAMES = {"ALL": "All 60", "lookup": "Lookup", "aggregation": "Aggregation",
             "business_definition": "Business\ndefinition", "time_fiscal": "Time /\nfiscal"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUES = LinearSegmentedColormap.from_list("blues", ["#f3f7fd", "#9ec5f4", "#3987e5", "#184f95", "#0d366b"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
})


def _pct_axis(ax, top=1.08):
    ax.set_ylim(0, top)
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", visible=False)


def _legend(ax, conditions, loc="upper center", ncol=4, anchor=(0.5, -0.12)):
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[c]) for c in conditions]
    ax.legend(handles, [NAMES[c] for c in conditions], loc=loc, ncol=ncol, frameon=False,
              bbox_to_anchor=anchor, fontsize=9, handlelength=1.2)


def _bar_labels(ax, xs, vals, his, color, dark_text=False, fontsize=7.5):
    """Value inside the bar (on a patch of the bar colour, so the whisker passes behind it);
    for short bars, just above the CI whisker."""
    for xv, v, hi in zip(xs, vals, his):
        if v >= 0.08:
            ax.text(xv, v / 2, f"{v * 100:.0f}", ha="center", va="center", fontsize=fontsize,
                    color=INK if dark_text else "white", fontweight="bold", zorder=5,
                    bbox=dict(boxstyle="round,pad=0.18", facecolor=color, edgecolor="none"))
        else:
            ax.text(xv, max(v, hi) + 0.015, f"{v * 100:.0f}", ha="center", va="bottom", fontsize=fontsize,
                    color=INK, fontweight="bold")


def _save(fig, path):
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_accuracy_by_category(summary, path, title="Execution accuracy by question category"):
    """summary: columns condition, category, accuracy, ci_low, ci_high."""
    fig, ax = plt.subplots(figsize=(10, 4.6))
    conds = [c for c in CONDITIONS if c in set(summary.condition)]
    w = 0.8 / len(conds)
    x = np.arange(len(CATEGORIES))
    for i, c in enumerate(conds):
        d = summary[summary.condition == c].set_index("category").reindex(CATEGORIES)
        xs = x - 0.4 + w * (i + 0.5)
        ax.bar(xs, d.accuracy, width=w, color=COLORS[c], edgecolor=SURFACE, linewidth=1.5)
        ax.errorbar(xs, d.accuracy, yerr=[d.accuracy - d.ci_low, d.ci_high - d.accuracy],
                    fmt="none", ecolor=INK2, elinewidth=0.9, capsize=2)
        _bar_labels(ax, xs, d.accuracy, d.ci_high, COLORS[c], dark_text=(c == "C_nosyn"))
    ax.set_xticks(x)
    ax.set_xticklabels([CAT_NAMES[c] for c in CATEGORIES])
    _pct_axis(ax)
    ax.set_title(title, pad=24)
    ax.text(0, 1.025, "Share of 3 runs × questions answered with the right number. Whiskers: 95% bootstrap CI (resampling questions).",
            transform=ax.transAxes, fontsize=8.5, color=INK2)
    _legend(ax, conds)
    return _save(fig, path)


def fig_outcomes(outcomes, path):
    """outcomes: columns condition, status, share (shares per condition sum to 1)."""
    fig, ax = plt.subplots(figsize=(10, 3.2))
    conds = [c for c in CONDITIONS if c in set(outcomes.condition)][::-1]
    order = ["correct", "silent_wrong", "empty", "error"]
    for yi, c in enumerate(conds):
        left = 0
        d = outcomes[outcomes.condition == c].set_index("status").reindex(order).fillna(0)
        for s in order:
            v = float(d.loc[s, "share"])
            if v <= 0:
                continue
            ax.barh(yi, v, left=left, color=STATUS[s], edgecolor=SURFACE, linewidth=2, height=0.62)
            if v >= 0.05:
                ax.text(left + v / 2, yi, f"{v * 100:.0f}%", ha="center", va="center", fontsize=8.5,
                        color="white" if s in ("correct", "silent_wrong") else INK, fontweight="bold")
            left += v
    ax.set_yticks(range(len(conds)))
    ax.set_yticklabels([NAMES[c] for c in conds])
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="y", visible=False)
    ax.set_title("What happened to every generated query")
    handles = [plt.Rectangle((0, 0), 1, 1, color=STATUS[s]) for s in order]
    ax.legend(handles, [STATUS_NAMES[s] for s in order], ncol=4, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14), fontsize=9, handlelength=1.2)
    return _save(fig, path)


def fig_failure_taxonomy(failures, path):
    """failures: columns condition, label, n (count of failed generations)."""
    pivot = failures.pivot_table(index="label", columns="condition", values="n", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(columns=[c for c in CONDITIONS if c in pivot.columns])
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(8.5, 0.42 * len(pivot) + 1.6))
    vmax = max(1, pivot.values.max())
    ax.imshow(pivot.values, cmap=BLUES, vmin=0, vmax=vmax, aspect="auto")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = int(pivot.values[i, j])
            ax.text(j, i, str(v) if v else "·", ha="center", va="center", fontsize=9,
                    color="white" if v > vmax * 0.55 else INK)
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels([NAMES[c].replace(", ", ",\n") for c in pivot.columns], fontsize=8.5)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels([l.replace("_", " ") for l in pivot.index])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("Why queries failed (count of failed generations)")
    return _save(fig, path)


def fig_judge(judge, path):
    """judge: columns condition, judge_agreement, judge_false_positive_rate."""
    conds = [c for c in CONDITIONS if c in set(judge.condition)]
    d = judge.set_index("condition").reindex(conds)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    panels = [("judge_agreement", "Judge agrees with execution"),
              ("judge_false_positive_rate", "Judge approves a WRONG answer")]
    for ax, (col, title) in zip(axes, panels):
        ax.bar(range(len(conds)), d[col], color=[COLORS[c] for c in conds], edgecolor=SURFACE, linewidth=1.5, width=0.62)
        for i, v in enumerate(d[col]):
            ax.text(i, v + 0.02, f"{v * 100:.0f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.set_xticks(range(len(conds)))
        ax.set_xticklabels([NAMES[c].split(":")[0] for c in conds])
        _pct_axis(ax)
        ax.set_title(title, fontsize=11)
    _legend(axes[0], conds, anchor=(1.1, -0.12))
    fig.suptitle("Can an LLM judge replace execution-based scoring?", x=0.07, ha="left", fontweight="bold", y=1.03)
    return _save(fig, path)


def fig_wording(wording, path):
    """wording: columns condition, wording, accuracy, ci_low, ci_high."""
    kinds = ["explicit", "canonical", "synonym"]
    kind_names = {"explicit": "Explicit\n(spelled out)", "canonical": "Canonical\n(official term)",
                  "synonym": "Synonym\n(\"sales\", \"income\")"}
    conds = [c for c in CONDITIONS if c in set(wording.condition)]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    w = 0.8 / len(conds)
    x = np.arange(len(kinds))
    for i, c in enumerate(conds):
        d = wording[wording.condition == c].set_index("wording").reindex(kinds)
        xs = x - 0.4 + w * (i + 0.5)
        ax.bar(xs, d.accuracy, width=w, color=COLORS[c], edgecolor=SURFACE, linewidth=1.5)
        ax.errorbar(xs, d.accuracy, yerr=[d.accuracy - d.ci_low, d.ci_high - d.accuracy],
                    fmt="none", ecolor=INK2, elinewidth=0.9, capsize=2)
        _bar_labels(ax, xs, d.accuracy, d.ci_high, COLORS[c], dark_text=(c == "C_nosyn"))
    ax.set_xticks(x)
    ax.set_xticklabels([kind_names[k] for k in kinds])
    _pct_axis(ax, top=1.12)
    ax.set_title("H3: accuracy by how the question is worded")
    _legend(ax, conds)
    return _save(fig, path)


def fig_cost(cost, path):
    """cost: columns condition, avg_input_tokens, accuracy."""
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for _, r in cost.iterrows():
        ax.scatter(r.avg_input_tokens, r.accuracy, s=90, color=COLORS[r.condition], edgecolor=SURFACE, linewidth=2, zorder=3)
        ax.annotate(f"{NAMES[r.condition]}\n{r.accuracy * 100:.0f}% · {r.avg_input_tokens:,.0f} tokens",
                    (r.avg_input_tokens, r.accuracy), textcoords="offset points", xytext=(8, -4), fontsize=8.5)
    ax.set_xlabel("Average prompt size (input tokens per question)")
    _pct_axis(ax)
    ax.set_xlim(0, cost.avg_input_tokens.max() * 1.45)
    ax.grid(axis="x", visible=True)
    ax.set_title("Accuracy vs prompt cost")
    return _save(fig, path)