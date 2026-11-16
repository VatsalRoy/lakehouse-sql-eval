# Databricks notebook source
# MAGIC %md
# MAGIC # Regression gate
# MAGIC Fails the job (triggering the failure email) if condition C regresses.
# MAGIC Every run is recorded in `eval.gate_history`, pass or fail.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("min_accuracy", "0.75")
dbutils.widgets.text("max_silent_wrong", "0.12")
dbutils.widgets.text("max_drop", "0.05")

CATALOG = dbutils.widgets.get("catalog")
MIN_ACC = float(dbutils.widgets.get("min_accuracy"))
MAX_SILENT = float(dbutils.widgets.get("max_silent_wrong"))
MAX_DROP = float(dbutils.widgets.get("max_drop"))

from datetime import datetime, timezone

spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.eval.gate_history (
  checked_at TIMESTAMP, condition STRING, accuracy DOUBLE, silent_wrong_rate DOUBLE,
  baseline_accuracy DOUBLE, passed BOOLEAN, reasons STRING)""")

rows = {r.condition: r for r in spark.sql(f"""
  SELECT condition, accuracy, silent_wrong_rate FROM {CATALOG}.eval.summary WHERE category = 'ALL'""").collect()}
c = rows["C_metric_view"]

baseline = spark.sql(f"""
  SELECT accuracy FROM {CATALOG}.eval.gate_history
  WHERE condition = 'C_metric_view' AND passed ORDER BY checked_at DESC LIMIT 1""").collect()
baseline_acc = baseline[0].accuracy if baseline else None

reasons = []
if c.accuracy < MIN_ACC:
    reasons.append(f"accuracy {c.accuracy:.1%} below floor {MIN_ACC:.0%}")
if c.silent_wrong_rate > MAX_SILENT:
    reasons.append(f"silent-wrong rate {c.silent_wrong_rate:.1%} above ceiling {MAX_SILENT:.0%}")
if baseline_acc is not None and baseline_acc - c.accuracy > MAX_DROP:
    reasons.append(f"accuracy dropped {baseline_acc - c.accuracy:.1%} vs last passing run ({baseline_acc:.1%})")
passed = not reasons

spark.createDataFrame(
    [(datetime.now(timezone.utc), "C_metric_view", float(c.accuracy), float(c.silent_wrong_rate),
      baseline_acc, passed, "; ".join(reasons) or "ok")],
    "checked_at TIMESTAMP, condition STRING, accuracy DOUBLE, silent_wrong_rate DOUBLE, "
    "baseline_accuracy DOUBLE, passed BOOLEAN, reasons STRING",
).write.mode("append").saveAsTable(f"{CATALOG}.eval.gate_history")

for cond, r in sorted(rows.items()):
    print(f"{cond:14} accuracy {r.accuracy:6.1%}  silent-wrong {r.silent_wrong_rate:5.1%}")
if not passed:
    raise Exception("REGRESSION GATE FAILED: " + "; ".join(reasons))
print("Gate passed.")