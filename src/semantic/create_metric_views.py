# Databricks notebook source
# MAGIC %md
# MAGIC # Create the metric views (the semantic layer)
# MAGIC Reads every `*.yaml` in `src/semantic/`, fills in the catalog, and runs
# MAGIC `CREATE OR REPLACE VIEW ... WITH METRICS LANGUAGE YAML`.
# MAGIC Also creates a `*_nosyn` copy with synonyms, display names and comments removed (the H3 ablation).

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("semantic_dir", "")
CATALOG = dbutils.widgets.get("catalog")
SEMANTIC_DIR = dbutils.widgets.get("semantic_dir")

import copy
import glob
import os
import yaml

AGENT_METADATA = ("synonyms", "display_name", "comment", "format")


def strip_metadata(spec: dict) -> dict:
    """Ablation: keep the logic (source, joins, filter, expressions), drop everything written for humans/agents."""
    s = copy.deepcopy(spec)
    s.pop("comment", None)
    for section in ("dimensions", "measures"):
        for item in s.get(section, []):
            for key in AGENT_METADATA:
                item.pop(key, None)
    return s


def create_metric_view(name: str, yaml_text: str):
    full_name = f"{CATALOG}.gold.{name}"
    spark.sql(f"CREATE OR REPLACE VIEW {full_name}\nWITH METRICS\nLANGUAGE YAML\nAS $$\n{yaml_text}\n$$")
    print(f"Created metric view {full_name}")


files = sorted(glob.glob(os.path.join(SEMANTIC_DIR, "*.yaml")))
assert files, f"No YAML files found in {SEMANTIC_DIR}"
for path in files:
    name = os.path.splitext(os.path.basename(path))[0]
    text = open(path).read().replace("{{catalog}}", CATALOG)
    create_metric_view(name, text)
    no_syn = yaml.safe_dump(strip_metadata(yaml.safe_load(text)), sort_keys=False, width=1000)
    create_metric_view(f"{name}_nosyn", no_syn)

# COMMAND ----------

# Smoke test: one query against each view.
display(spark.sql(f"""
  SELECT fiscal_year,
         MEASURE(gross_revenue) AS gross_revenue,
         MEASURE(net_revenue)   AS net_revenue,
         MEASURE(refund_rate)   AS refund_rate,
         MEASURE(active_customers) AS active_customers
  FROM {CATALOG}.gold.sales_metrics
  GROUP BY fiscal_year ORDER BY fiscal_year"""))
display(spark.sql(f"""
  SELECT category, MEASURE(product_gross_revenue) AS revenue, MEASURE(units_sold) AS units
  FROM {CATALOG}.gold.product_sales_metrics
  WHERE fiscal_year = 2025 GROUP BY category ORDER BY revenue DESC"""))