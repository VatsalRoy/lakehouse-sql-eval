# Databricks notebook source
# MAGIC %md
# MAGIC # Apply data-catalog comments to the gold tables
# MAGIC Source of truth: `src/catalog/column_comments.yaml` (also what the condition-B prompt uses).
# MAGIC Gold tables are pipeline-managed materialized views, so some ALTER/COMMENT statements may be refused.
# MAGIC This step is best-effort: it never fails the job, it reports what was applied.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")

import os
import yaml

docs = yaml.safe_load(open(os.path.join(REPO_ROOT, "src", "catalog", "column_comments.yaml")))


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def try_sql(*statements):
    """Try each equivalent statement until one works. Returns (ok, last_error)."""
    err = None
    for st in statements:
        try:
            spark.sql(st)
            return True, None
        except Exception as e:  # noqa: BLE001
            err = str(e).splitlines()[0][:200]
    return False, err

# COMMAND ----------

applied, failed = 0, []
for table, tdoc in docs["tables"].items():
    full = f"{CATALOG}.gold.{table}"
    ok, err = try_sql(f"COMMENT ON TABLE {full} IS '{esc(tdoc['comment'])}'")
    applied += ok
    if not ok:
        failed.append((full, err))
    for col, text in tdoc["columns"].items():
        ok, err = try_sql(
            f"COMMENT ON COLUMN {full}.`{col}` IS '{esc(text)}'",
            f"ALTER TABLE {full} ALTER COLUMN `{col}` COMMENT '{esc(text)}'",
            f"ALTER MATERIALIZED VIEW {full} ALTER COLUMN `{col}` COMMENT '{esc(text)}'",
        )
        applied += ok
        if not ok:
            failed.append((f"{full}.{col}", err))

print(f"Applied {applied} comments; {len(failed)} could not be applied.")
for name, err in failed[:10]:
    print(" -", name, "->", err)
if failed:
    print("\nThat is OK: the condition-B prompt reads the YAML file directly, so the experiment is unaffected.")