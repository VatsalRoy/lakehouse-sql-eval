"""Text-to-SQL evaluation console (Databricks App).

Reads the evaluation tables written by the evaluate_sql and analyze_results jobs and renders
the story-led console view. Every number on the page is computed from those tables.
"""
import json
import os
import time
from collections import Counter, defaultdict

from flask import Flask, render_template, request

app = Flask(__name__)

CATALOG = os.getenv("EVAL_CATALOG", "workspace")
CACHE_SECONDS = 600

CONDITIONS = [
    {"id": "A_raw", "key": "A", "label": "raw schema", "color": "#8b95a5"},
    {"id": "B_comments", "key": "B", "label": "+ column comments", "color": "#c9d1dc"},
    {"id": "C_metric_view", "key": "C", "label": "metric view", "color": "#34d399"},
    {"id": "C_nosyn", "key": "C−", "label": "metric view, no synonyms", "color": "#1f8f68"},
]
BY_ID = {c["id"]: c for c in CONDITIONS}
CATEGORIES = [
    ("business_definition", "Business definition", "net revenue, AOV, refund rate"),
    ("time_fiscal", "Time / fiscal", "fiscal quarters, months"),
    ("lookup", "Lookup", "single facts"),
    ("aggregation", "Aggregation", "raw record counts"),
    ("ALL", "All 60 questions", "overall"),
]
LABEL_NAMES = {
    "wrong_definition": "Wrong business definition", "runtime_error": "Runtime error",
    "fan_out_join": "Fan-out join (double count)", "null_arithmetic": "NULL arithmetic",
    "over_applied_definition": "Over-applied definition", "extra_filter": "Extra filter",
    "wrong_time_grain": "Calendar vs fiscal", "unit_or_scale": "Unit or scale",
    "wrong_grouping": "Wrong grouping key", "wrong_aggregation": "Wrong aggregation",
    "empty_result": "Empty result", "other": "Other",
}
# Curated example cards: (question_id, condition, question, explanation). Numbers are read from eval.scores.
EXAMPLES = [
    ("B02", "A_raw", "What were our total sales in FY2025?", "Refunds were never subtracted and internal test accounts were counted. Too high, and nothing looked broken."),
    ("B01", "B_comments", "What was total net revenue in FY2025?", "SUM(order − refund) made every order without a refund NULL, so most of the revenue silently disappeared."),
    ("B08", "B_comments", "What was the refund rate in FY2025?", "Divided refunds by refunded orders only, and dated them by refund instead of order."),
]

# ----------------------------------------------------------------------------- data access
_cache = {"at": 0.0, "data": None}


def _query(sql):
    from databricks import sql as dbsql
    from databricks.sdk.core import Config

    cfg = Config()
    with dbsql.connect(server_hostname=cfg.host,
                       http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
                       credentials_provider=lambda: cfg.authenticate) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_tables():
    if os.getenv("LOCAL_FIXTURE"):
        with open(os.path.join(os.path.dirname(__file__), "fixture.json")) as f:
            return json.load(f)
    if _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    e = f"{CATALOG}.eval"
    data = {
        "summary": _query(f"SELECT condition, category, accuracy, ci_low, ci_high, silent_share_of_failures FROM {e}.summary"),
        "diffs": _query(f"SELECT comparison, category, diff, ci_low, ci_high, significant FROM {e}.paired_diffs"),
        "wording": _query(f"SELECT condition, wording, accuracy FROM {e}.summary_by_wording"),
        "scores": _query(f"""SELECT question_id, category, condition, seed, status, execution_match, judge_correct,
                                    est_input_tokens, pred_preview, gold_preview FROM {e}.scores"""),
        "failures": _query(f"SELECT condition, category, label FROM {e}.failures"),
        "meta": _query(f"""SELECT CAST(MAX(generated_at) AS STRING) AS last_run, COUNT(*) AS n,
                                  MAX(endpoint) AS endpoint FROM {e}.generations"""),
    }
    _cache.update(at=time.time(), data=data)
    return data


# ----------------------------------------------------------------------------- formatting helpers
def pct(x):
    return int(round(float(x) * 100))


def signed_pts(x):
    v = int(round(float(x) * 100))
    return ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v)} pts"


def fmt_value(v):
    """Money in millions, ratios as percent, counts with separators."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f) >= 100_000:
        return f"${f / 1e6:,.2f}M"
    if 0 < abs(f) < 1.5:
        return f"{f * 100:.1f}%"
    return f"{f:,.0f}"


def first_value(preview):
    try:
        rows = json.loads(preview)
        return rows[0][-1] if rows and rows[0] else None
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- view model
def build_view(data, category="ALL"):
    summ = {(r["condition"], r["category"]): r for r in data["summary"]}
    diffs = {(r["comparison"], r["category"]): r for r in data["diffs"]}
    a_all, c_all = summ[("A_raw", "ALL")], summ[("C_metric_view", "ALL")]
    ca, ba = diffs[("C_metric_view - A_raw", "ALL")], diffs[("B_comments - A_raw", "ALL")]

    hero = {
        "a": pct(a_all["accuracy"]), "c": pct(c_all["accuracy"]),
        "gain": signed_pts(ca["diff"]),
        "gain_ci": f"95% CI {signed_pts(ca['ci_low']).replace(' pts', '')} to {signed_pts(ca['ci_high']).replace(' pts', '')}",
        "gain_sig": "significant" if ca["significant"] else "not significant",
        "silent": pct(a_all["silent_share_of_failures"] or 0),
        "b_gain": signed_pts(ba["diff"]).replace(" pts", ""),
        "b_sig": "significant" if ba["significant"] else "not significant",
    }

    rows = []
    for cat_id, name, note in CATEGORIES:
        vals = [pct(summ[(c["id"], cat_id)]["accuracy"]) for c in CONDITIONS]
        a, c = vals[0], vals[2]
        gain = c - a
        dots = []
        for i in (1, 3, 0, 2):
            size = 14 if i in (0, 2) else 10
            dots.append({"v": vals[i], "color": CONDITIONS[i]["color"], "size": size,
                         "offset": -(size / 2) - 2, "top": 15 - size / 2 - 2,
                         "title": f"{CONDITIONS[i]['key']}: {vals[i]}%"})
        rows.append({
            "name": name, "note": note, "dots": dots,
            "line_left": min(a, c), "line_width": abs(gain),
            "line_color": "rgba(52,211,153,0.45)" if gain >= 0 else "rgba(255,123,114,0.5)",
            "delta": ("+" if gain > 0 else "−" if gain < 0 else "±") + f"{abs(gain)} pts",
            "delta_color": "#34d399" if gain > 0 else "#ff7b72" if gain < 0 else "#9aa3ae",
            "delta_bg": "#0f2a20" if gain > 0 else "#2a1316" if gain < 0 else "#1a1e25",
        })

    # Examples: first silent-wrong generation for each curated (question, condition)
    examples = []
    for qid, cond, question, why in EXAMPLES:
        hit = next((s for s in sorted(data["scores"], key=lambda s: s["seed"])
                    if s["question_id"] == qid and s["condition"] == cond and s["status"] == "silent_wrong"), None)
        if hit:
            examples.append({"id": qid, "cond": BY_ID[cond]["key"], "q": question,
                             "model": fmt_value(first_value(hit["pred_preview"])),
                             "truth": fmt_value(first_value(hit["gold_preview"])), "why": why})

    # Category filter applies to outcomes, failure reasons and the judge panel
    scores = [s for s in data["scores"] if category == "ALL" or s["category"] == category]
    fails = [f for f in data["failures"] if category == "ALL" or f["category"] == category]

    outcomes, reasons, judge = [], [], []
    for c in CONDITIONS:
        sc = [s for s in scores if s["condition"] == c["id"]]
        n = max(len(sc), 1)
        correct = round(100 * sum(s["status"] == "correct" for s in sc) / n)
        silent = round(100 * sum(s["status"] == "silent_wrong" for s in sc) / n)
        error = max(0, 100 - correct - silent)
        outcomes.append({**c, "correct": correct, "silent": silent, "error": error,
                         "silent_label": (f"{silent}% silent wrong" if silent >= 18 else f"{silent}%" if silent >= 5 else ""),
                         "error_label": f"{error}%" if error >= 5 else ""})

        fc = Counter(f["label"] for f in fails if f["condition"] == c["id"])
        total = max(sum(fc.values()), 1)
        reasons.append({**c, "items": [{"name": LABEL_NAMES.get(l, l), "pct": round(100 * k / total)}
                                       for l, k in fc.most_common(2)]})

        wrong = [s for s in sc if not s["execution_match"] and s["judge_correct"] is not None]
        fp = round(100 * sum(bool(s["judge_correct"]) for s in wrong) / max(len(wrong), 1))
        judge.append({**c, "fp": fp})

    judge_ratio = (judge[2]["fp"] / judge[0]["fp"]) if judge[0]["fp"] else 0

    word = {(r["condition"], r["wording"]): pct(r["accuracy"]) for r in data["wording"]}
    synonym = [{**c, "v": word.get((c["id"], "synonym"), 0)} for c in CONDITIONS]
    syn_drop = synonym[2]["v"] - synonym[3]["v"]

    tok = defaultdict(list)
    for s in data["scores"]:
        tok[s["condition"]].append(s["est_input_tokens"] or 0)
    cost = []
    for c in CONDITIONS:
        t = tok[c["id"]]
        cost.append({**c, "tokens": f"{(sum(t) / max(len(t), 1)):,.0f}", "acc": f"{pct(summ[(c['id'], 'ALL')]['accuracy'])}%"})
    a_tok = sum(tok["A_raw"]) / max(len(tok["A_raw"]), 1)
    c_tok = sum(tok["C_metric_view"]) / max(len(tok["C_metric_view"]), 1)

    meta = data["meta"][0]
    return {
        "conditions": CONDITIONS, "hero": hero, "rows": rows, "examples": examples,
        "outcomes": outcomes, "reasons": reasons, "judge": judge,
        "judge_note": f"Wrong queries that use the metric view look governed, so the judge trusts them {judge_ratio:.1f}× as often.",
        "synonym": synonym, "syn_note": f"Removing synonyms and descriptions (C−) cost {syn_drop} points on these questions.",
        "cost": cost, "cost_note": f"C costs about {c_tok / max(a_tok, 1):.0f}× the prompt of A. Cheap next to one wrong revenue number in a board deck.",
        "category": category, "categories": [(k, n) for k, n, _ in CATEGORIES if k != "ALL"],
        "last_run": (meta.get("last_run") or "")[:16], "n_generations": meta.get("n", 0),
        "model": (meta.get("endpoint") or "").replace("databricks-", ""),
    }


@app.route("/")
def index():
    category = request.args.get("category", "ALL")
    valid = {k for k, _, _ in CATEGORIES}
    if category not in valid:
        category = "ALL"
    return render_template("index.html", **build_view(load_tables(), category))


@app.route("/healthz")
def healthz():
    return "ok"