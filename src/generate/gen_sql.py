# Databricks notebook source
# MAGIC %md
# MAGIC # Generate SQL with ai_query for every (question x condition x seed)
# MAGIC 1. Build one prompt per row (4 conditions: A_raw, B_comments, C_metric_view, C_nosyn)
# MAGIC 2. Register each condition's template in the MLflow Prompt Registry (best-effort)
# MAGIC 3. Call the LLM **from SQL** with `ai_query` - only for rows not already generated (safe to re-run after quota errors)
# MAGIC 4. Append results to `eval.generations`

# COMMAND ----------

# MAGIC %pip install --quiet --upgrade "mlflow[databricks]>=3.1.0"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
dbutils.widgets.text("llm_endpoint", "")
dbutils.widgets.text("conditions", "A_raw,B_comments,C_metric_view,C_nosyn")
dbutils.widgets.text("seeds", "3")
dbutils.widgets.text("limit_questions", "60")
dbutils.widgets.text("temperature", "0.2")
dbutils.widgets.text("max_tokens", "1500")

CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")
ENDPOINT = dbutils.widgets.get("llm_endpoint")
CONDITIONS = [c.strip() for c in dbutils.widgets.get("conditions").split(",") if c.strip()]
SEEDS = int(dbutils.widgets.get("seeds"))
LIMIT_Q = int(dbutils.widgets.get("limit_questions"))
TEMPERATURE = float(dbutils.widgets.get("temperature"))
MAX_TOKENS = int(dbutils.widgets.get("max_tokens"))
assert ENDPOINT, "Set llm_endpoint (databricks.yml variable llm_endpoint)"

import glob
import json
import os
import sys
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "generate"))
import prompts  # noqa: E402

# COMMAND ----------

# Inputs: questions, schema of the 6 gold tables, catalog comments, metric view YAML
questions = [json.loads(l) for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))][:LIMIT_Q]
GOLD_TABLES = ["dim_customer", "dim_product", "dim_date", "fact_orders", "fact_order_items", "fact_refunds"]

cols = spark.sql(f"""
  SELECT table_name, column_name, upper(full_data_type) AS data_type
  FROM {CATALOG}.information_schema.columns
  WHERE table_schema = 'gold' AND table_name IN ({",".join(f"'{t}'" for t in GOLD_TABLES)})
  ORDER BY table_name, ordinal_position""").collect()
schema = {t: [(r.column_name, r.data_type) for r in cols if r.table_name == t] for t in GOLD_TABLES}
assert all(schema.values()), f"Missing gold tables: {[t for t, c in schema.items() if not c]}"

comments = yaml.safe_load(open(os.path.join(REPO_ROOT, "src", "catalog", "column_comments.yaml")))
metric_views = {
    os.path.splitext(os.path.basename(p))[0]: open(p).read().replace("{{catalog}}", CATALOG)
    for p in sorted(glob.glob(os.path.join(REPO_ROOT, "src", "semantic", "*.yaml")))
}

templates = {c: prompts.condition_template(prompts.build_context(c, schema, CATALOG, comments, metric_views))
             for c in CONDITIONS}
for c, t in templates.items():
    print(f"{c:14} template ~{len(t) // 4} tokens")

# COMMAND ----------

# Register templates in the MLflow Prompt Registry (Unity Catalog). Best-effort: generation continues if this fails.
import mlflow

mlflow.set_registry_uri("databricks-uc")
registry_versions = {}
for c, t in templates.items():
    try:
        p = mlflow.genai.register_prompt(
            name=f"{CATALOG}.eval.text2sql_{c.lower()}",
            template=t,
            commit_message=f"template {prompts.TEMPLATE_VERSION}",
            tags={"condition": c, "template_version": prompts.TEMPLATE_VERSION},
        )
        registry_versions[c] = str(p.version)
        print(f"Registered {c} as version {p.version}")
    except Exception as e:  # noqa: BLE001
        registry_versions[c] = None
        print(f"Prompt Registry skipped for {c}: {str(e).splitlines()[0][:150]}")

# COMMAND ----------

# One row per (question, condition, seed)
rows = []
for q in questions:
    for c in CONDITIONS:
        prompt = prompts.render(templates[c], q["question"])
        ph = prompts.prompt_hash(prompt)
        for seed in range(1, SEEDS + 1):
            rows.append(dict(
                gen_key=f"{q['id']}|{c}|{seed}|{ph}|{ENDPOINT}|{TEMPERATURE}",
                question_id=q["id"], category=q["category"], wording=q["wording"], condition=c, seed=seed,
                prompt=prompt, prompt_hash=ph, prompt_chars=len(prompt), est_input_tokens=len(prompt) // 4,
                template_version=prompts.TEMPLATE_VERSION, registry_version=registry_versions.get(c),
                endpoint=ENDPOINT, temperature=TEMPERATURE,
            ))
PROMPT_COLS = ["gen_key", "question_id", "category", "wording", "condition", "seed", "prompt", "prompt_hash",
               "prompt_chars", "est_input_tokens", "template_version", "registry_version", "endpoint", "temperature"]
PROMPT_SCHEMA = ("gen_key STRING, question_id STRING, category STRING, wording STRING, condition STRING, seed INT, "
                 "prompt STRING, prompt_hash STRING, prompt_chars INT, est_input_tokens INT, template_version STRING, "
                 "registry_version STRING, endpoint STRING, temperature DOUBLE")
spark.createDataFrame([tuple(r[k] for k in PROMPT_COLS) for r in rows], PROMPT_SCHEMA).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.eval.prompts")
print(f"{len(rows)} prompts written to {CATALOG}.eval.prompts")

# COMMAND ----------

# Only generate what's missing (or previously failed). Makes the notebook safe to re-run after quota/rate-limit errors.
spark.sql(f"""
  CREATE TABLE IF NOT EXISTS {CATALOG}.eval.generations (
    gen_key STRING, question_id STRING, category STRING, wording STRING, condition STRING, seed INT,
    prompt_hash STRING, prompt_chars INT, est_input_tokens INT, template_version STRING, registry_version STRING,
    endpoint STRING, temperature DOUBLE, response STRING, error STRING, generated_sql STRING,
    response_chars INT, generated_at TIMESTAMP)""")

todo = spark.sql(f"""
  SELECT p.* FROM {CATALOG}.eval.prompts p
  LEFT ANTI JOIN (SELECT gen_key FROM {CATALOG}.eval.generations WHERE error IS NULL AND generated_sql IS NOT NULL) g
  USING (gen_key)""")
n_todo = todo.count()
print(f"{n_todo} rows to generate")

# COMMAND ----------

if n_todo:
    todo.createOrReplaceTempView("todo")
    out = spark.sql(f"""
      SELECT *, ai_query(
          '{ENDPOINT}', prompt,
          failOnError => false,
          modelParameters => named_struct('temperature', {TEMPERATURE}, 'max_tokens', {MAX_TOKENS})
        ) AS r
      FROM todo""").collect()

    now = datetime.now(timezone.utc)
    results = []
    for row in out:
        d = row.asDict()
        r = d.pop("r")
        d.pop("prompt")
        rd = r.asDict() if r else {}
        response = prompts.response_text(rd.get("result", rd.get("response")))
        error = rd.get("errorMessage", rd.get("errorStatus")) if r else "no response"
        sql = prompts.extract_sql(response)
        if error is None and sql is None:
            error = "no_sql_in_response"   # counts as a failure, so a re-run retries it
        d.update(response=response, error=error,
                 generated_sql=sql, response_chars=len(response or ""), generated_at=now)
        results.append(d)

    # replace earlier failed attempts for the same keys, then append the new results
    keys = [r["gen_key"] for r in results]
    spark.createDataFrame([(k,) for k in keys], "gen_key STRING").createOrReplaceTempView("new_keys")
    spark.sql(f"DELETE FROM {CATALOG}.eval.generations WHERE gen_key IN (SELECT gen_key FROM new_keys)")
    gen_schema = spark.table(f"{CATALOG}.eval.generations").schema
    spark.createDataFrame([tuple(r[f.name] for f in gen_schema.fields) for r in results], gen_schema) \
        .write.mode("append").saveAsTable(f"{CATALOG}.eval.generations")

# COMMAND ----------

summary = spark.sql(f"""
  SELECT condition,
         COUNT(*) AS generations,
         SUM(CASE WHEN error IS NULL AND generated_sql IS NOT NULL THEN 1 ELSE 0 END) AS ok,
         SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
         ROUND(AVG(est_input_tokens)) AS avg_input_tokens
  FROM {CATALOG}.eval.generations
  WHERE endpoint = '{ENDPOINT}' AND temperature = {TEMPERATURE}
  GROUP BY condition ORDER BY condition""")
display(summary)
errors = spark.sql(f"SELECT error, COUNT(*) n FROM {CATALOG}.eval.generations WHERE error IS NOT NULL GROUP BY error ORDER BY n DESC LIMIT 5")
display(errors)