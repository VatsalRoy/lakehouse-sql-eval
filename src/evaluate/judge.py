# Databricks notebook source
# MAGIC %md
# MAGIC # LLM judge: "Does this SQL correctly answer the question?"
# MAGIC The judge sees what a human reviewer would see: the same context the generator had, the question and the SQL.
# MAGIC It does NOT see the query result or the gold answer. We later measure how often it agrees with execution (H2).
# MAGIC Resumable: only judges generations not yet judged by this judge endpoint + judge prompt version.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
dbutils.widgets.text("llm_endpoint", "")
dbutils.widgets.text("judge_endpoint", "")
dbutils.widgets.text("max_tokens", "400")

CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")
ENDPOINT = dbutils.widgets.get("llm_endpoint")
JUDGE = dbutils.widgets.get("judge_endpoint") or ENDPOINT
MAX_TOKENS = int(dbutils.widgets.get("max_tokens"))

import glob
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "generate"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "evaluate"))
import prompts  # noqa: E402
import scorers  # noqa: E402

# COMMAND ----------

# Same context-building as gen_sql.py, so the judge sees exactly what the generator saw
GOLD_TABLES = ["dim_customer", "dim_product", "dim_date", "fact_orders", "fact_order_items", "fact_refunds"]
cols = spark.sql(f"""
  SELECT table_name, column_name, upper(full_data_type) AS data_type
  FROM {CATALOG}.information_schema.columns
  WHERE table_schema = 'gold' AND table_name IN ({",".join(f"'{t}'" for t in GOLD_TABLES)})
  ORDER BY table_name, ordinal_position""").collect()
schema = {t: [(r.column_name, r.data_type) for r in cols if r.table_name == t] for t in GOLD_TABLES}
comments = yaml.safe_load(open(os.path.join(REPO_ROOT, "src", "catalog", "column_comments.yaml")))
metric_views = {
    os.path.splitext(os.path.basename(p))[0]: open(p).read().replace("{{catalog}}", CATALOG)
    for p in sorted(glob.glob(os.path.join(REPO_ROOT, "src", "semantic", "*.yaml")))
}
contexts = {c: prompts.build_context(c, schema, CATALOG, comments, metric_views) for c in prompts.CONDITIONS}
qtext = {json.loads(l)["id"]: json.loads(l)["question"]
         for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))}

# COMMAND ----------

gens = spark.sql(f"""
  SELECT gen_key, condition, question_id, generated_sql FROM {CATALOG}.eval.generations
  WHERE endpoint = '{ENDPOINT}' AND generated_sql IS NOT NULL""").collect()
rows = [(f"{g.gen_key}|{JUDGE}|{prompts.JUDGE_VERSION}", g.gen_key, JUDGE, prompts.JUDGE_VERSION,
         prompts.render_judge(contexts[g.condition], qtext[g.question_id], g.generated_sql)) for g in gens]
spark.createDataFrame(rows, "jkey STRING, gen_key STRING, judge_endpoint STRING, judge_version STRING, prompt STRING") \
    .createOrReplaceTempView("judge_prompts")

spark.sql(f"""
  CREATE TABLE IF NOT EXISTS {CATALOG}.eval.judgments (
    jkey STRING, gen_key STRING, judge_endpoint STRING, judge_version STRING,
    judge_response STRING, judge_error STRING, judge_correct BOOLEAN)""")
todo = spark.sql(f"""
  SELECT p.* FROM judge_prompts p
  LEFT ANTI JOIN (SELECT jkey FROM {CATALOG}.eval.judgments WHERE judge_error IS NULL AND judge_correct IS NOT NULL) j
  USING (jkey)""")
todo.createOrReplaceTempView("judge_todo")
n_todo = todo.count()
print(f"{len(rows)} generations, {n_todo} to judge with {JUDGE}")

# COMMAND ----------

if n_todo:
    out = spark.sql(f"""
      SELECT jkey, gen_key, judge_endpoint, judge_version,
             ai_query('{JUDGE}', prompt, failOnError => false,
                      modelParameters => named_struct('temperature', 0.0, 'max_tokens', {MAX_TOKENS})) AS r
      FROM judge_todo""").collect()
    res = []
    for o in out:
        rd = o.r.asDict() if o.r else {}
        text = prompts.response_text(rd.get("result", rd.get("response")))
        err = rd.get("errorMessage", rd.get("errorStatus")) if o.r else "no response"
        verdict = scorers.parse_verdict(text)
        if err is None and verdict is None:
            err = "unparseable_verdict"
        res.append((o.jkey, o.gen_key, o.judge_endpoint, o.judge_version, text, err, verdict))
    spark.createDataFrame([(r[0],) for r in res], "jkey STRING").createOrReplaceTempView("new_jkeys")
    spark.sql(f"DELETE FROM {CATALOG}.eval.judgments WHERE jkey IN (SELECT jkey FROM new_jkeys)")
    spark.createDataFrame(res, spark.table(f"{CATALOG}.eval.judgments").schema) \
        .write.mode("append").saveAsTable(f"{CATALOG}.eval.judgments")

display(spark.sql(f"""
  SELECT judge_endpoint, COUNT(*) AS judged,
         SUM(CASE WHEN judge_correct THEN 1 ELSE 0 END) AS said_correct,
         SUM(CASE WHEN judge_error IS NOT NULL THEN 1 ELSE 0 END) AS errors
  FROM {CATALOG}.eval.judgments GROUP BY judge_endpoint"""))