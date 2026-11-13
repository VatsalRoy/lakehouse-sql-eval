# Databricks notebook source
# MAGIC %md
# MAGIC # Validate the medallion pipeline
# MAGIC 1. Row-count and sanity checks (fails the job if something is badly wrong)
# MAGIC 2. Data-quality report from the pipeline's expectations
# MAGIC 3. "Trap demo": four plausible answers to "What was FY2025 revenue?"

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
CATALOG = dbutils.widgets.get("catalog")
C = CATALOG

def one(sql):
    return spark.sql(sql).collect()[0][0]

# COMMAND ----------

checks = []
def check(name, value, ok, expected):
    checks.append((name, str(value), expected, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {value}  (expected {expected})")

raw_orders = one(f"SELECT COUNT(*) FROM {C}.bronze.orders_raw")
silver_orders = one(f"SELECT COUNT(*) FROM {C}.silver.orders")
distinct_orders = one(f"SELECT COUNT(DISTINCT order_id) FROM {C}.silver.orders")
check("bronze has duplicates", raw_orders, raw_orders > silver_orders, "> silver count")
check("silver orders unique", f"{silver_orders} rows / {distinct_orders} ids", silver_orders == distinct_orders, "equal")
check("silver orders count", silver_orders, 199_000 <= silver_orders <= 200_000, "199k-200k (bad rows dropped)")

customers = one(f"SELECT COUNT(*) FROM {C}.silver.customers")
check("customers deduplicated", customers, customers == 25_000, "25000")

refund_rate = one(f"SELECT COUNT(*) / (SELECT COUNT(*) FROM {C}.gold.fact_orders) FROM {C}.gold.fact_refunds")
check("refund rate", round(refund_rate, 4), 0.07 <= refund_rate <= 0.09, "0.07-0.09")

missing_fx = one(f"SELECT COUNT(*) FROM {C}.gold.fact_orders WHERE order_total_usd IS NULL")
check("every order has an FX rate", missing_fx, missing_fx == 0, "0 missing")

orphans = one(f"""SELECT COUNT(*) FROM {C}.gold.fact_orders o
                  LEFT ANTI JOIN {C}.gold.dim_customer c ON c.customer_id = o.customer_id""")
check("every order has a customer", orphans, orphans == 0, "0 orphans")

test_accts = one(f"SELECT COUNT(*) FROM {C}.gold.dim_customer WHERE is_test_account")
deleted = one(f"SELECT COUNT(*) FROM {C}.gold.dim_customer WHERE is_deleted")
check("test accounts present (trap)", test_accts, test_accts > 0, "> 0")
check("soft-deleted customers present (trap)", deleted, deleted > 0, "> 0")

fys = sorted(r[0] for r in spark.sql(f"""SELECT DISTINCT d.fiscal_year FROM {C}.gold.fact_orders o
                                         JOIN {C}.gold.dim_date d ON d.date = o.order_date""").collect())
check("fiscal years covered", fys, fys == [2024, 2025, 2026], "[2024, 2025, 2026]")

line_total = one(f"""SELECT ROUND(ABS(SUM(o.order_total_local) - (SELECT SUM(line_amount_local) FROM {C}.gold.fact_order_items)), 0)
                     FROM {C}.gold.fact_orders o""")
check("order totals match line items", line_total, line_total < 1000, "diff < 1000 (rounding)")

spark.createDataFrame(checks, "check STRING, value STRING, expected STRING, passed BOOLEAN") \
    .write.mode("overwrite").saveAsTable(f"{C}.eval.data_checks")

# COMMAND ----------

# Data-quality report: pass/fail counts for every expectation in the latest pipeline update.
try:
    latest = one(f"""SELECT origin.update_id FROM event_log(TABLE({C}.silver.orders))
                     WHERE event_type = 'create_update' ORDER BY timestamp DESC LIMIT 1""")
    dq = spark.sql(f"""
        WITH ev AS (
          SELECT explode(from_json(details:flow_progress:data_quality:expectations,
                 'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) AS e
          FROM event_log(TABLE({C}.silver.orders))
          WHERE event_type = 'flow_progress'
            AND origin.update_id = '{latest}'
            AND details:flow_progress:data_quality:expectations IS NOT NULL
        )
        SELECT e.dataset, e.name AS expectation,
               SUM(e.passed_records) AS passed, SUM(e.failed_records) AS failed
        FROM ev GROUP BY 1, 2 ORDER BY failed DESC, dataset""")
    dq.write.mode("overwrite").saveAsTable(f"{C}.eval.dq_report")
    display(dq)
except Exception as err:
    print("Could not read the pipeline event log here; see the pipeline's Data quality tab instead.\n", err)

# COMMAND ----------

# Trap demo: same question, four plausible SQL answers.
trap = spark.sql(f"""
WITH o AS (
  SELECT o.*, c.is_test_account
  FROM {C}.gold.fact_orders o
  JOIN {C}.gold.dim_customer c USING (customer_id)
  JOIN {C}.gold.dim_date d ON d.date = o.order_date
  WHERE d.fiscal_year = 2025
),
r AS (
  SELECT order_id, SUM(refund_amount_usd) AS refunded FROM {C}.gold.fact_refunds GROUP BY order_id
)
SELECT '1. naive: SUM(order_total_local)' AS answer, ROUND(SUM(order_total_local), 0) AS fy2025_revenue FROM o
UNION ALL
SELECT '2. converted to USD', ROUND(SUM(order_total_usd), 0) FROM o
UNION ALL
SELECT '3. USD, completed, no test accounts', ROUND(SUM(order_total_usd), 0)
FROM o WHERE status = 'completed' AND NOT is_test_account
UNION ALL
SELECT '4. NET: also minus refunds', ROUND(SUM(order_total_usd - COALESCE(r.refunded, 0)), 0)
FROM o LEFT JOIN r USING (order_id) WHERE status = 'completed' AND NOT is_test_account
""")
display(trap)

# COMMAND ----------

failed = [c for c in checks if not c[3]]
if failed:
    raise Exception(f"{len(failed)} data check(s) failed: {[c[0] for c in failed]}")
print("All data checks passed.")