# Databricks notebook source
# Phase 1 smoke test: checks schemas exist and the LLM endpoint answers.

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("llm_endpoint", "")
catalog = dbutils.widgets.get("catalog")
endpoint = dbutils.widgets.get("llm_endpoint")

# COMMAND ----------

# 1) Are all four schemas there?
existing = {row[0] for row in spark.sql(f"SHOW SCHEMAS IN {catalog}").collect()}
required = {"bronze", "silver", "gold", "eval"}
missing = required - existing
if missing:
    raise Exception(f"Missing schemas in {catalog}: {missing}")
print(f"OK: schemas found -> {sorted(required)}")

# COMMAND ----------

# 2) Can we call the LLM from SQL?
answer = spark.sql(
    f"SELECT ai_query('{endpoint}', 'Reply with exactly the word: pong') AS a"
).collect()[0]["a"]
print(f"OK: LLM replied -> {answer!r}")

# COMMAND ----------

# 3) Can we write a Delta table? (we'll do this constantly later)
spark.sql(f"""
  CREATE OR REPLACE TABLE {catalog}.eval.setup_check AS
  SELECT current_timestamp() AS checked_at, '{endpoint}' AS llm_endpoint
""")
print(f"OK: wrote {catalog}.eval.setup_check")