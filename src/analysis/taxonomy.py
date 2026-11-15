"""Failure taxonomy: label WHY a generated query got the wrong answer.

Rule-based and transparent (every label comes with the evidence that triggered it).
Rules are heuristics, so the notebook also produces a review sample to spot-check by hand.

Labels (one primary per failure, plus all flags that matched):
  runtime_error          query failed to run
  empty_result           ran, returned nothing
  unit_or_scale          right number, wrong unit (e.g. 1.32 instead of 132%)
  over_applied_definition governed metric view used for a raw-records question (filters it shouldn't have)
  null_arithmetic        SUM(a - b) where b can be NULL -> rows silently vanish
  fan_out_join           order-level amounts duplicated by joining to line items or refunds
  wrong_time_grain       calendar vs fiscal mix-up, or filtering on the refund date
  wrong_definition       missing a business rule (refunds, test accounts, completed status)
  extra_filter           added a business filter the question did not ask for
  wrong_grouping         grouped by a non-unique name instead of the key
  wrong_aggregation      wrong grain/aggregate (e.g. AVG(line_number), one row per order instead of a total)
  other
"""
import re

LABELS = ["runtime_error", "empty_result", "unit_or_scale", "over_applied_definition", "null_arithmetic",
          "fan_out_join", "wrong_time_grain", "wrong_definition", "extra_filter", "wrong_grouping", "wrong_aggregation", "other"]

_MONTHS = r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b"


def _has(sql, pattern):
    return re.search(pattern, sql or "", re.I | re.S) is not None


def _single_number(rows):
    if len(rows) == 1 and len(rows[0]) >= 1:
        try:
            return float(rows[0][-1])
        except (TypeError, ValueError):
            return None
    return None


def _answer_part(gold_sql):
    """The parts of the gold SQL that compute the answer (SELECT list + ORDER BY), not the shared FROM/JOIN block."""
    head = re.split(r"\bFROM\b", gold_sql, maxsplit=1, flags=re.I)[0]
    tail = re.split(r"\bORDER BY\b", gold_sql, flags=re.I)[-1] if re.search(r"\bORDER BY\b", gold_sql, re.I) else ""
    return head + " " + tail


def label_failure(status, condition, category, question, gold_sql, sql, pred_rows, gold_rows, pred_n_rows=None):
    """Return (primary_label, flags: list[str], evidence: str). Only call for failures."""
    sql = sql or ""
    q = question.lower()
    flags, evidence = [], {}

    if status == "error":
        return "runtime_error", ["runtime_error"], "query failed to execute"
    if status == "empty":
        return "empty_result", ["empty_result"], "no rows returned"

    # unit / scale: a single number off by exactly x100 (or /100)
    p, g = _single_number(pred_rows), _single_number(gold_rows)
    if p and g:
        for f in (100.0, 0.01):
            if abs(p * f - g) <= 0.005 * abs(g) + 1e-9:
                flags.append("unit_or_scale")
                evidence["unit_or_scale"] = f"{p} x {f:g} = {g}"

    # governed view used where the question wanted raw records
    if condition.startswith("C") and category in ("lookup", "aggregation") and _has(sql, r"_metrics(_nosyn)?\b"):
        flags.append("over_applied_definition")
        evidence["over_applied_definition"] = "metric view (test accounts / non-completed orders excluded) used for a raw-records question"

    # NULL arithmetic: SUM(x - y) with a refund column and no NULL handling
    if _has(sql, r"SUM\(\s*[\w.]+\s*-\s*[\w.]*refund[\w.]*\s*\)") and not _has(sql, r"\b(COALESCE|IFNULL|NVL|ZEROIFNULL)\b"):
        flags.append("null_arithmetic")
        evidence["null_arithmetic"] = "SUM(a - refund) without COALESCE: orders without refunds become NULL and drop out"

    # fan-out: line items joined to refunds, or order totals summed after joining line items
    joins_items = _has(sql, r"fact_order_items")
    if joins_items and (_has(sql, r"fact_refunds") or _has(sql, r"SUM\([^)]*order_total")):
        flags.append("fan_out_join")
        evidence["fan_out_join"] = "order-level amounts repeated once per line item"

    # time grain
    wants_calendar = "calendar" in q or re.search(_MONTHS, q) is not None
    wants_fiscal = (not wants_calendar) and re.search(r"\b(fy\d{4}|fiscal|q[1-4]|quarter)\b", q) is not None
    if wants_fiscal and _has(sql, r"calendar_(quarter|year|month)|\bQUARTER\s*\(|\bYEAR\s*\(|'\d{4}-01-01'"):
        flags.append("wrong_time_grain")
        evidence["wrong_time_grain"] = "fiscal period asked, calendar dates used"
    if wants_calendar and _has(sql, r"fiscal_(quarter|year|month)") and not _has(sql, r"calendar_"):
        flags.append("wrong_time_grain")
        evidence["wrong_time_grain"] = "calendar period asked, fiscal dates used"
    if _has(sql, r"refund_date\s*=|ON\s+[\w.]*refund_date"):
        flags.append("wrong_time_grain")
        evidence["wrong_time_grain"] = "period taken from refund date instead of order date"

    # missing business rules (compare against what the gold SQL needed)
    missing = []
    if _has(_answer_part(gold_sql), r"refund") and not _has(sql, r"refund") and not _has(sql, r"MEASURE\((net_revenue|refunds|refund_rate|average_order_value)"):
        missing.append("refunds not subtracted")
    if _has(gold_sql, r"is_test_account") and not _has(sql, r"is_test_account|test\.internal|_metrics"):
        missing.append("test accounts included")
    if _has(gold_sql, r"status\s*=\s*'completed'") and not _has(sql, r"completed|_metrics"):
        missing.append("non-completed orders included")
    if missing:
        flags.append("wrong_definition")
        evidence["wrong_definition"] = "; ".join(missing)

    # extra business filters on a raw-records question
    if not _has(gold_sql, r"is_test_account|is_deleted|completed") and _has(sql, r"is_test_account|is_deleted|'completed'"):
        flags.append("extra_filter")
        evidence["extra_filter"] = "added test/deleted/status filter the question did not ask for"

    if _has(gold_sql, r"GROUP BY[^;]*product_id") and _has(sql, r"GROUP BY\s+[\w.]*product_name\s*(ORDER|$|\n)") :
        flags.append("wrong_grouping")
        evidence["wrong_grouping"] = "grouped by product_name (not unique) instead of product_id"

    n_pred = pred_n_rows if pred_n_rows is not None else len(pred_rows)
    if (len(gold_rows) == 1 and n_pred > 1) or _has(sql, r"AVG\(\s*[\w.]*line_number"):
        flags.append("wrong_aggregation")
        evidence["wrong_aggregation"] = f"{n_pred} rows returned where one total was expected" if n_pred > 1 else "averaged line numbers instead of counting lines"

    flags = list(dict.fromkeys(flags))  # unique, keep order
    for label in LABELS:
        if label in flags:
            return label, flags, evidence[label]
    return "other", ["other"], "no rule matched - review manually"