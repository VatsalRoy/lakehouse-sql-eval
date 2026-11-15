"""Cases taken from real failures in this project's evaluation run."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "analysis"))
import taxonomy  # noqa: E402

NET_GOLD = """SELECT ROUND(SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)), 2)
FROM workspace.gold.fact_orders o JOIN workspace.gold.dim_customer c ON c.customer_id = o.customer_id
LEFT JOIN (SELECT order_id, SUM(refund_amount_usd) AS refund_usd FROM workspace.gold.fact_refunds GROUP BY order_id) r ON r.order_id = o.order_id
WHERE o.status = 'completed' AND NOT c.is_test_account AND d.fiscal_year = 2025"""
COUNT_GOLD = NET_GOLD.replace("ROUND(SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)), 2)", "COUNT(*)")


def lab(sql, gold=NET_GOLD, cond="A_raw", cat="business_definition", q="What was net revenue in FY2025?",
        pred=((1.0,),), goldrows=((7316265.52,),), status="silent_wrong", n=None):
    return taxonomy.label_failure(status, cond, cat, q, gold, sql, list(pred), list(goldrows), n)


def test_null_arithmetic():
    sql = "SELECT SUM(fo.order_total_usd - fr.refund_amount_usd) FROM workspace.gold.fact_orders fo LEFT JOIN x fr"
    assert lab(sql)[0] == "null_arithmetic"


def test_fan_out_join():
    sql = ("SELECT SUM(oi.line_amount_usd) - SUM(r.refund_amount_usd) FROM workspace.gold.fact_order_items oi "
           "LEFT JOIN workspace.gold.fact_refunds r ON oi.order_id = r.order_id")
    assert lab(sql)[0] == "fan_out_join"


def test_wrong_definition_lists_missing_rules():
    label, _, ev = lab("SELECT SUM(order_total_usd) FROM workspace.gold.fact_orders")
    assert label == "wrong_definition" and "refunds" in ev and "test accounts" in ev


def test_count_question_does_not_claim_missing_refunds():
    label, _, ev = lab("SELECT COUNT(*) FROM workspace.gold.fact_orders o WHERE NOT is_test_account", gold=COUNT_GOLD)
    assert label == "wrong_definition" and "refund" not in ev


def test_fiscal_vs_calendar():
    sql = "SELECT SUM(x) FROM t WHERE calendar_year = 2025 AND calendar_quarter = 3 AND is_test_account AND status='completed' AND refund"
    assert lab(sql, q="What was revenue in Q3 2025?")[0] == "wrong_time_grain"


def test_refund_date_filter():
    sql = "SELECT SUM(refund_amount_usd) / SUM(o.order_total_usd) FROM r JOIN d ON r.refund_date = d.date"
    assert "wrong_time_grain" in lab(sql)[1]


def test_unit_or_scale():
    assert lab("SELECT growth", pred=((1.315942,),), goldrows=((131.59,),), cond="C_metric_view",
               cat="time_fiscal")[0] == "unit_or_scale"


def test_over_applied_definition():
    sql = "SELECT currency, COUNT(1) FROM workspace.gold.sales_metrics GROUP BY currency"
    assert lab(sql, gold="SELECT currency, COUNT(*) FROM workspace.gold.fact_orders GROUP BY currency",
               cond="C_metric_view", cat="aggregation")[0] == "over_applied_definition"


def test_extra_filter():
    sql = "SELECT region, COUNT(customer_id) FROM workspace.gold.dim_customer WHERE is_deleted = FALSE GROUP BY region"
    assert lab(sql, gold="SELECT region, COUNT(*) FROM workspace.gold.dim_customer GROUP BY region",
               cat="aggregation")[0] == "extra_filter"


def test_wrong_grouping():
    sql = "SELECT p.product_name, SUM(q) FROM i JOIN p GROUP BY p.product_name ORDER BY 2 DESC LIMIT 5"
    gold = "SELECT p.product_name, SUM(i.quantity) FROM i JOIN p GROUP BY p.product_id, p.product_name"
    assert lab(sql, gold=gold, cat="aggregation")[0] == "wrong_grouping"


def test_wrong_aggregation():
    assert lab("SELECT AVG(line_number) FROM workspace.gold.fact_order_items",
               gold="SELECT ROUND(a / b, 4)", cat="aggregation")[0] == "wrong_aggregation"
    assert lab("SELECT COUNT(order_id) FROM i GROUP BY order_id HAVING COUNT(*) > 3",
               gold="SELECT COUNT(*) FROM (...) t", cat="aggregation", n=29963)[0] == "wrong_aggregation"


def test_errors_and_empty():
    assert lab("SELECT bad", status="error")[0] == "runtime_error"
    assert lab("SELECT 1", status="empty")[0] == "empty_result"