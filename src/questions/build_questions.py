"""Builds src/questions/questions.jsonl: 60 benchmark questions with gold SQL.

Run from the repo root:  python src/questions/build_questions.py

Each question has:
  id, category (lookup | aggregation | business_definition | time_fiscal),
  question, gold_sql (raw gold tables, hand-written answer key),
  mv_sql (same answer via the metric view, or null), wording (canonical | synonym | explicit),
  trap (what makes it hard), ordered (does row order matter?)
"""
import json
from pathlib import Path

G = "workspace.gold"
MV = f"{G}.sales_metrics"
PMV = f"{G}.product_sales_metrics"

# Reusable pieces of the answer key, straight from docs/business_rules.md
NET_FROM = f"""FROM {G}.fact_orders o
JOIN {G}.dim_customer c ON c.customer_id = o.customer_id
JOIN {G}.dim_date d ON d.date = o.order_date
LEFT JOIN (SELECT order_id, SUM(refund_amount_usd) AS refund_usd
           FROM {G}.fact_refunds GROUP BY order_id) r ON r.order_id = o.order_id
WHERE o.status = 'completed' AND NOT c.is_test_account"""
NET = "ROUND(SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)), 2)"
GROSS = "ROUND(SUM(o.order_total_usd), 2)"
REFUNDS = "ROUND(SUM(COALESCE(r.refund_usd, 0)), 2)"
ACTIVE = "COUNT(DISTINCT CASE WHEN NOT c.is_deleted THEN o.customer_id END)"
AOV = "ROUND(SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)) / COUNT(*), 2)"
RATE = "ROUND(SUM(COALESCE(r.refund_usd, 0)) / SUM(o.order_total_usd), 4)"

LINE_FROM = f"""FROM {G}.fact_order_items i
JOIN {G}.fact_orders o ON o.order_id = i.order_id
JOIN {G}.dim_customer c ON c.customer_id = o.customer_id
JOIN {G}.dim_product p ON p.product_id = i.product_id
JOIN {G}.dim_date d ON d.date = o.order_date
WHERE o.status = 'completed' AND NOT c.is_test_account"""

Q = []
def q(id, category, question, gold_sql, mv_sql=None, wording="explicit", trap="", ordered=False):
    Q.append(dict(id=id, category=category, question=question, gold_sql=gold_sql.strip(),
                  mv_sql=mv_sql.strip() if mv_sql else None, wording=wording, trap=trap, ordered=ordered))

# ---------------------------------------------------------------- LOOKUP (15)
# Simple, unambiguous facts. The semantic layer should barely matter here.
L = "lookup"
q("L01", L, "How many products are in the Electronics category?",
  f"SELECT COUNT(*) FROM {G}.dim_product WHERE category = 'Electronics'")
q("L02", L, "How many customer accounts are registered in Germany (country code DE), including deleted and test accounts?",
  f"SELECT COUNT(*) FROM {G}.dim_customer WHERE country = 'DE'")
q("L03", L, "What is the highest list price of any product, in USD?",
  f"SELECT MAX(list_price_usd) FROM {G}.dim_product")
q("L04", L, "Which product has the highest list price?",
  f"SELECT product_name FROM {G}.dim_product ORDER BY list_price_usd DESC LIMIT 1")
q("L05", L, "How many distinct product categories are there?",
  f"SELECT COUNT(DISTINCT category) FROM {G}.dim_product")
q("L06", L, "What currency was order 1000500 placed in?",
  f"SELECT currency FROM {G}.fact_orders WHERE order_id = 1000500")
q("L07", L, "What is the status of order 1000123?",
  f"SELECT status FROM {G}.fact_orders WHERE order_id = 1000123")
q("L08", L, "How many line items does order 1000777 have?",
  f"SELECT COUNT(*) FROM {G}.fact_order_items WHERE order_id = 1000777")
q("L09", L, "Which country is customer 100042 from?",
  f"SELECT country FROM {G}.dim_customer WHERE customer_id = 100042")
q("L10", L, "How many customer accounts are flagged as internal test accounts?",
  f"SELECT COUNT(*) FROM {G}.dim_customer WHERE is_test_account")
q("L11", L, "How many customer accounts have been soft-deleted?",
  f"SELECT COUNT(*) FROM {G}.dim_customer WHERE is_deleted")
q("L12", L, "How many products are marked inactive?",
  f"SELECT COUNT(*) FROM {G}.dim_product WHERE NOT is_active")
q("L13", L, "On what date did customer 100007 sign up?",
  f"SELECT signup_date FROM {G}.dim_customer WHERE customer_id = 100007")
q("L14", L, "What was the order total of order 1000999 in its own (local) currency?",
  f"SELECT order_total_local FROM {G}.fact_orders WHERE order_id = 1000999")
q("L15", L, "How many refund records have the reason 'damaged'?",
  f"SELECT COUNT(*) FROM {G}.fact_refunds WHERE reason = 'damaged'")

# ----------------------------------------------------------- AGGREGATION (15)
# Group-bys and joins with explicit scope. Traps are grain and joins, not definitions.
A = "aggregation"
q("A01", A, "How many order records are there for each order status?",
  f"SELECT status, COUNT(*) FROM {G}.fact_orders GROUP BY status")
q("A02", A, "How many customer accounts are there in each region?",
  f"SELECT region, COUNT(*) FROM {G}.dim_customer GROUP BY region")
q("A03", A, "How many products are in each category?",
  f"SELECT category, COUNT(*) FROM {G}.dim_product GROUP BY category")
q("A04", A, "What is the average list price per product category, in USD?",
  f"SELECT category, ROUND(AVG(list_price_usd), 2) FROM {G}.dim_product GROUP BY category")
q("A05", A, "What is the total number of units ordered per product category, across all order lines regardless of status?",
  f"""SELECT p.category, SUM(i.quantity)
FROM {G}.fact_order_items i JOIN {G}.dim_product p ON p.product_id = i.product_id
GROUP BY p.category""", trap="join lines to products, not orders")
q("A06", A, "Which 5 products have the most units ordered across all order lines? Return product name and units.",
  f"""SELECT p.product_name, SUM(i.quantity) AS units
FROM {G}.fact_order_items i JOIN {G}.dim_product p ON p.product_id = i.product_id
GROUP BY p.product_id, p.product_name ORDER BY units DESC LIMIT 5""", trap="product names are not unique: group by product_id", ordered=True)
q("A07", A, "How many refunds were recorded for each refund reason?",
  f"SELECT reason, COUNT(*) FROM {G}.fact_refunds GROUP BY reason")
q("A08", A, "On average, how many line items does an order have (across all orders)?",
  f"SELECT ROUND((SELECT COUNT(*) FROM {G}.fact_order_items) / (SELECT COUNT(*) FROM {G}.fact_orders), 4)",
  trap="grain: lines per order, not AVG(line_number)")
q("A09", A, "How many order records are there in each currency?",
  f"SELECT currency, COUNT(*) FROM {G}.fact_orders GROUP BY currency")
q("A10", A, "How many distinct customers have placed at least one order through the mobile channel (any status)?",
  f"SELECT COUNT(DISTINCT customer_id) FROM {G}.fact_orders WHERE channel = 'mobile'",
  trap="distinct customers, not orders")
q("A11", A, "What is the total refunded amount in USD for each refund reason (all refund records)?",
  f"SELECT reason, ROUND(SUM(refund_amount_usd), 2) FROM {G}.fact_refunds GROUP BY reason",
  trap="use the USD column, not local")
q("A12", A, "How many customer accounts signed up in each calendar year?",
  f"SELECT YEAR(signup_date), COUNT(*) FROM {G}.dim_customer GROUP BY YEAR(signup_date)")
q("A13", A, "Which country has the most customer accounts?",
  f"SELECT country FROM {G}.dim_customer GROUP BY country ORDER BY COUNT(*) DESC LIMIT 1")
q("A14", A, "What is the total line-item value in USD per product category, summed over every order line in the data (any status, any customer)?",
  f"""SELECT p.category, ROUND(SUM(i.line_amount_usd), 2)
FROM {G}.fact_order_items i JOIN {G}.dim_product p ON p.product_id = i.product_id
GROUP BY p.category""", trap="joining orders and summing order_total double-counts")
q("A15", A, "How many orders contain more than 3 line items?",
  f"""SELECT COUNT(*) FROM (SELECT order_id FROM {G}.fact_order_items
GROUP BY order_id HAVING COUNT(*) > 3) t""")

# --------------------------------------------------- BUSINESS DEFINITION (15)
# Natural business wording. Correct answers require the rules in docs/business_rules.md.
B = "business_definition"
q("B01", B, "What was total net revenue in FY2025?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "refunds, test accounts, status, FX, fiscal year")
q("B02", B, "What were our total sales in FY2025?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2025",
  "synonym", "'sales' means net revenue")
q("B03", B, "What was gross revenue in FY2025?",
  f"SELECT {GROSS}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(gross_revenue) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "gross still excludes test accounts and non-completed orders")
q("B04", B, "How much money did we make in FY2026?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2026",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2026",
  "synonym", "'money we made' means net revenue")
q("B05", B, "How many active customers did we have in FY2025?",
  f"SELECT {ACTIVE}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(active_customers) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "exclude deleted and test; needs a completed order")
q("B06", B, "What was the average order value in FY2025?",
  f"SELECT {AOV}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(average_order_value) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "net revenue / completed orders")
q("B07", B, "What was our AOV in FY2024?",
  f"SELECT {AOV}\n{NET_FROM}\n  AND d.fiscal_year = 2024",
  f"SELECT MEASURE(average_order_value) FROM {MV} WHERE fiscal_year = 2024",
  "synonym", "abbreviation")
q("B08", B, "What was the refund rate in FY2025?",
  f"SELECT {RATE}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(refund_rate) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "by value, not by count")
q("B09", B, "What was net revenue by region in FY2026?",
  f"SELECT c.region, {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2026\nGROUP BY c.region",
  f"SELECT region, MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2026 GROUP BY region",
  "canonical")
q("B10", B, "Break down our FY2025 income by sales channel.",
  f"SELECT o.channel, {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2025\nGROUP BY o.channel",
  f"SELECT channel, MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2025 GROUP BY channel",
  "synonym", "'income' means net revenue")
q("B11", B, "What share of gross revenue was refunded in FY2026?",
  f"SELECT {RATE}\n{NET_FROM}\n  AND d.fiscal_year = 2026",
  f"SELECT MEASURE(refund_rate) FROM {MV} WHERE fiscal_year = 2026",
  "synonym", "this is the refund rate")
q("B12", B, "What was the total value of refunds, in USD, on orders placed in FY2025?",
  f"SELECT {REFUNDS}\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(refunds) FROM {MV} WHERE fiscal_year = 2025",
  "canonical", "refunds attributed to order date; test accounts excluded")
q("B13", B, "How many orders did we have in FY2025?",
  f"SELECT COUNT(*)\n{NET_FROM}\n  AND d.fiscal_year = 2025",
  f"SELECT MEASURE(completed_orders) FROM {MV} WHERE fiscal_year = 2025",
  "synonym", "'orders' means completed, non-test orders")
q("B14", B, "Which region brought in the most revenue in FY2024?",
  f"SELECT c.region\n{NET_FROM}\n  AND d.fiscal_year = 2024\nGROUP BY c.region ORDER BY SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)) DESC LIMIT 1",
  f"SELECT region FROM (SELECT region, MEASURE(net_revenue) AS nr FROM {MV} WHERE fiscal_year = 2024 GROUP BY region) ORDER BY nr DESC LIMIT 1",
  "synonym", "'revenue' means net; INR inflates naive sums")
q("B15", B, "What was gross revenue by product category in FY2025?",
  f"SELECT p.category, ROUND(SUM(i.line_amount_usd), 2)\n{LINE_FROM}\n  AND d.fiscal_year = 2025\nGROUP BY p.category",
  f"SELECT category, MEASURE(product_gross_revenue) FROM {PMV} WHERE fiscal_year = 2025 GROUP BY category",
  "canonical", "must use line amounts; refunds are not allocated to products")

# --------------------------------------------------------- TIME / FISCAL (15)
T = "time_fiscal"
q("T01", T, "What was revenue in Q3 2025?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2025 AND d.fiscal_quarter = 3",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2025 AND fiscal_quarter = 3",
  "synonym", "Q3 means fiscal Q3 (Aug-Oct 2024), not Jul-Sep 2025")
q("T02", T, "What was net revenue in calendar Q3 2024 (July to September 2024)?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.calendar_year = 2024 AND d.calendar_quarter = 3",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE calendar_year = 2024 AND calendar_quarter = 3",
  "canonical", "explicitly calendar")
q("T03", T, "Show net revenue for each fiscal quarter of FY2026.",
  f"SELECT d.fiscal_quarter, {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2026\nGROUP BY d.fiscal_quarter ORDER BY d.fiscal_quarter",
  f"SELECT fiscal_quarter, MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2026 GROUP BY fiscal_quarter ORDER BY fiscal_quarter",
  "canonical", ordered=True)
q("T04", T, "Which fiscal quarter of FY2025 had the highest net revenue?",
  f"SELECT d.fiscal_quarter\n{NET_FROM}\n  AND d.fiscal_year = 2025\nGROUP BY d.fiscal_quarter ORDER BY SUM(o.order_total_usd - COALESCE(r.refund_usd, 0)) DESC LIMIT 1",
  f"SELECT fiscal_quarter FROM (SELECT fiscal_quarter, MEASURE(net_revenue) AS nr FROM {MV} WHERE fiscal_year = 2025 GROUP BY fiscal_quarter) ORDER BY nr DESC LIMIT 1",
  "canonical")
q("T05", T, "What was net revenue in each fiscal year?",
  f"SELECT d.fiscal_year, {NET}\n{NET_FROM}\nGROUP BY d.fiscal_year ORDER BY d.fiscal_year",
  f"SELECT fiscal_year, MEASURE(net_revenue) FROM {MV} GROUP BY fiscal_year ORDER BY fiscal_year",
  "canonical", ordered=True)
q("T06", T, "What was net revenue in calendar year 2025?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.calendar_year = 2025",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE calendar_year = 2025",
  "canonical", "calendar, not fiscal")
q("T07", T, "How many active customers were there in Q4 of FY2026?",
  f"SELECT {ACTIVE}\n{NET_FROM}\n  AND d.fiscal_year = 2026 AND d.fiscal_quarter = 4",
  f"SELECT MEASURE(active_customers) FROM {MV} WHERE fiscal_year = 2026 AND fiscal_quarter = 4",
  "canonical", "FY2026 Q4 = Nov 2025-Jan 2026")
q("T08", T, "What was net revenue in January 2025?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.calendar_year = 2025 AND d.calendar_month = 1",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE calendar_year = 2025 AND calendar_month = 1",
  "canonical", "January 2025 is fiscal month 12 of FY2025")
q("T09", T, "What were sales in the second quarter of fiscal 2024?",
  f"SELECT {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2024 AND d.fiscal_quarter = 2",
  f"SELECT MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2024 AND fiscal_quarter = 2",
  "synonym", "fiscal Q2 FY2024 = May-Jul 2023")
q("T10", T, "Show monthly net revenue for FY2025, in fiscal month order.",
  f"SELECT d.fiscal_month, {NET}\n{NET_FROM}\n  AND d.fiscal_year = 2025\nGROUP BY d.fiscal_month ORDER BY d.fiscal_month",
  f"SELECT fiscal_month, MEASURE(net_revenue) FROM {MV} WHERE fiscal_year = 2025 GROUP BY fiscal_month ORDER BY fiscal_month",
  "canonical", "fiscal month 1 = February", ordered=True)
q("T11", T, "By what percentage did net revenue grow from FY2025 to FY2026?",
  f"""SELECT ROUND(100 * (SUM(CASE WHEN d.fiscal_year = 2026 THEN o.order_total_usd - COALESCE(r.refund_usd, 0) END)
       / SUM(CASE WHEN d.fiscal_year = 2025 THEN o.order_total_usd - COALESCE(r.refund_usd, 0) END) - 1), 2)
{NET_FROM}""",
  f"""SELECT ROUND(100 * (MAX(CASE WHEN fiscal_year = 2026 THEN nr END) / MAX(CASE WHEN fiscal_year = 2025 THEN nr END) - 1), 2)
FROM (SELECT fiscal_year, MEASURE(net_revenue) AS nr FROM {MV} GROUP BY fiscal_year)""",
  "canonical", "percentage, fiscal years")
q("T12", T, "What was gross revenue in fiscal Q1 of FY2026?",
  f"SELECT {GROSS}\n{NET_FROM}\n  AND d.fiscal_year = 2026 AND d.fiscal_quarter = 1",
  f"SELECT MEASURE(gross_revenue) FROM {MV} WHERE fiscal_year = 2026 AND fiscal_quarter = 1",
  "canonical", "FY2026 Q1 = Feb-Apr 2025")
q("T13", T, "What was the refund rate in Q4 FY2025?",
  f"SELECT {RATE}\n{NET_FROM}\n  AND d.fiscal_year = 2025 AND d.fiscal_quarter = 4",
  f"SELECT MEASURE(refund_rate) FROM {MV} WHERE fiscal_year = 2025 AND fiscal_quarter = 4",
  "canonical", "refunds follow the order date even if refunded next quarter")
q("T14", T, "What was the average order value in each fiscal quarter of FY2025?",
  f"SELECT d.fiscal_quarter, {AOV}\n{NET_FROM}\n  AND d.fiscal_year = 2025\nGROUP BY d.fiscal_quarter ORDER BY d.fiscal_quarter",
  f"SELECT fiscal_quarter, MEASURE(average_order_value) FROM {MV} WHERE fiscal_year = 2025 GROUP BY fiscal_quarter ORDER BY fiscal_quarter",
  "canonical", ordered=True)
q("T15", T, "How many orders were placed on weekends in FY2025?",
  f"SELECT COUNT(*)\n{NET_FROM}\n  AND d.fiscal_year = 2025 AND d.is_weekend",
  f"SELECT MEASURE(completed_orders) FROM {MV} WHERE fiscal_year = 2025 AND is_weekend",
  "synonym", "'orders' means completed non-test orders")

assert len(Q) == 60 and len({x["id"] for x in Q}) == 60
out = Path(__file__).parent / "questions.jsonl"
with open(out, "w") as f:
    for row in Q:
        f.write(json.dumps(row) + "\n")
print(f"Wrote {len(Q)} questions to {out}")