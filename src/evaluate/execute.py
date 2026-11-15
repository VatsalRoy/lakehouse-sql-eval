# Databricks notebook source
# MAGIC %md
# MAGIC # Execute gold SQL and every generated SQL
# MAGIC - Gold answers -> `eval.gold_results`
# MAGIC - Generated SQL -> `eval.executions` (status, row count, first 200 rows as JSON, runtime)
# MAGIC
# MAGIC Safety: LLM output is untrusted code. Only single read-only SELECT/WITH statements are run,
# MAGIC each with a timeout. Identical SQL strings are executed once and shared.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
dbutils.widgets.text("llm_endpoint", "")
dbutils.widgets.text("timeout_s", "60")
dbutils.widgets.text("workers", "8")

CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")
ENDPOINT = dbutils.widgets.get("llm_endpoint")
TIMEOUT_S = int(dbutils.widgets.get("timeout_s"))
WORKERS = int(dbutils.widgets.get("workers"))
MAX_FETCH = 10_001          # enough to know "way too many rows" without pulling huge results

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "evaluate"))
import scorers  # noqa: E402

questions = [json.loads(l) for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))]

# COMMAND ----------


def run_sql(sql: str):
    """Run one query with a timeout. Returns (status, n_rows, result_json, ms)."""
    if not scorers.is_safe_select(sql):
        return "error: blocked (not a single read-only SELECT)", 0, None, 0
    sql = sql.strip().rstrip(";").replace("workspace.", f"{CATALOG}.")
    tag = "eval_" + uuid.uuid4().hex[:12]
    timed_out = []

    def _interrupt():
        timed_out.append(True)
        try:
            spark.interruptTag(tag)
        except Exception:  # noqa: BLE001
            pass

    timer = threading.Timer(TIMEOUT_S, _interrupt)
    start = time.time()
    try:
        if hasattr(spark, "addTag"):
            spark.addTag(tag)          # tags are per-thread in Spark Connect, so each query can be interrupted alone
        timer.start()
        rows = [tuple(r) for r in spark.sql(sql).limit(MAX_FETCH).collect()]
        return "ok", len(rows), scorers.rows_to_json(rows), int((time.time() - start) * 1000)
    except Exception as e:  # noqa: BLE001
        msg = "timeout" if timed_out else "error: " + str(e).strip().splitlines()[0][:300]
        return msg, 0, None, int((time.time() - start) * 1000)
    finally:
        timer.cancel()
        if hasattr(spark, "removeTag"):
            try:
                spark.removeTag(tag)
            except Exception:  # noqa: BLE001
                pass

# COMMAND ----------

# 1) Gold answers
gold_rows = []
for q in questions:
    status, n, js, ms = run_sql(q["gold_sql"])
    assert status == "ok" and n > 0, f"Gold SQL for {q['id']} failed: {status}"
    gold_rows.append((q["id"], js, n, q["ordered"]))
spark.createDataFrame(gold_rows, "question_id STRING, gold_json STRING, gold_n_rows INT, ordered BOOLEAN") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.gold_results")
print(f"Gold answers stored for {len(gold_rows)} questions")

# COMMAND ----------

# 2) Generated SQL (deduplicated)
gens = spark.sql(f"""
  SELECT gen_key, question_id, condition, seed, generated_sql
  FROM {CATALOG}.eval.generations WHERE endpoint = '{ENDPOINT}'""").collect()
distinct_sql = sorted({g.generated_sql for g in gens if g.generated_sql})
print(f"{len(gens)} generations, {len(distinct_sql)} distinct SQL strings to execute with {WORKERS} workers")

t0 = time.time()
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    results = dict(zip(distinct_sql, pool.map(run_sql, distinct_sql)))
print(f"Executed in {time.time() - t0:.0f}s")

out = []
for g in gens:
    status, n, js, ms = results.get(g.generated_sql, ("no_sql", 0, None, 0)) if g.generated_sql else ("no_sql", 0, None, 0)
    sql_hash = hashlib.sha1((g.generated_sql or "").encode()).hexdigest()[:12]
    out.append((g.gen_key, g.question_id, g.condition, g.seed, sql_hash, status, n, js, ms))

spark.createDataFrame(out, "gen_key STRING, question_id STRING, condition STRING, seed INT, sql_hash STRING, "
                           "exec_status STRING, n_rows INT, result_json STRING, exec_ms INT") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.executions")

display(spark.sql(f"""
  SELECT condition,
         SUM(CASE WHEN exec_status = 'ok' THEN 1 ELSE 0 END) AS ran,
         SUM(CASE WHEN exec_status LIKE 'error%' THEN 1 ELSE 0 END) AS errors,
         SUM(CASE WHEN exec_status = 'timeout' THEN 1 ELSE 0 END) AS timeouts
  FROM {CATALOG}.eval.executions GROUP BY condition ORDER BY condition"""))