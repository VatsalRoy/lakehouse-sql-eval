# Databricks notebook source
# MAGIC %md
# MAGIC # Validate the benchmark
# MAGIC For every question: the gold SQL must run and return rows.
# MAGIC Where a metric-view query exists, it must return the SAME answer as the gold SQL.
# MAGIC A mismatch means a bug in the business definitions (yours or the YAML's). Investigate, don't hide it.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")

import json
import os
import sys

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "evaluate"))
from compare import results_match  # noqa: E402

questions = [json.loads(l) for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))]
print(f"Loaded {len(questions)} questions")


def run(sql):
    return [tuple(r) for r in spark.sql(sql.replace("workspace.", f"{CATALOG}.")).collect()]

# COMMAND ----------

results = []
for q in questions:
    row = {"id": q["id"], "category": q["category"], "gold_rows": None, "gold_ok": False,
           "mv_checked": False, "mv_match": None, "detail": "", "gold_answer": ""}
    try:
        gold = run(q["gold_sql"])
        row["gold_rows"] = len(gold)
        row["gold_ok"] = len(gold) > 0 and gold[0][0] is not None
        row["gold_answer"] = str(gold[:3])[:300]
        if q["mv_sql"]:
            row["mv_checked"] = True
            mv = run(q["mv_sql"])
            row["mv_match"], row["detail"] = results_match(gold, mv, ordered=q["ordered"])
    except Exception as e:
        row["detail"] = f"ERROR: {str(e)[:300]}"
    status = "OK " if row["gold_ok"] and row["mv_match"] in (None, True) else "BAD"
    print(f"{status} {q['id']:4} gold_rows={row['gold_rows']} mv={row['mv_match']} {row['detail'] if status == 'BAD' else ''}")
    results.append(row)

schema = "id STRING, category STRING, gold_rows INT, gold_ok BOOLEAN, mv_checked BOOLEAN, mv_match BOOLEAN, detail STRING, gold_answer STRING"
df = spark.createDataFrame([tuple(r[k] for k in ["id", "category", "gold_rows", "gold_ok", "mv_checked", "mv_match", "detail", "gold_answer"]) for r in results], schema)
df.write.mode("overwrite").saveAsTable(f"{CATALOG}.eval.question_checks")
display(df)

# COMMAND ----------

bad = [r["id"] for r in results if not r["gold_ok"] or r["mv_match"] is False]
checked = sum(r["mv_checked"] for r in results)
if bad:
    raise Exception(f"{len(bad)} question(s) failed validation: {bad}")
print(f"All 60 gold queries ran. {checked} metric-view answers match the gold SQL.")