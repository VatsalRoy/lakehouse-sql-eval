# Databricks notebook source
# MAGIC %md
# MAGIC # Phase 6 analysis
# MAGIC 1. Failure taxonomy for every wrong answer -> `eval.failures` (+ a 25-row sample to check by hand -> `eval.failure_review`)
# MAGIC 2. Judge confusion matrix -> `eval.judge_confusion`
# MAGIC 3. Consistency across the 3 seeds -> `eval.consistency`
# MAGIC 4. Cost (tokens) vs accuracy -> `eval.cost`
# MAGIC 5. Report figures -> Volume `eval.artifacts/figures` and MLflow

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "analysis"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "evaluate"))
import figures  # noqa: E402
import scorers  # noqa: E402
import taxonomy  # noqa: E402

questions = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))}
gold = {r.question_id: scorers.rows_from_json(r.gold_json) for r in spark.table(f"{CATALOG}.eval.gold_results").collect()}

scores = spark.sql(f"""
  SELECT s.*, e.result_json, g.response_chars
  FROM {CATALOG}.eval.scores s
  LEFT JOIN {CATALOG}.eval.executions e USING (gen_key)
  LEFT JOIN {CATALOG}.eval.generations g USING (gen_key)""").toPandas()
print(f"{len(scores)} scored generations")

# COMMAND ----------

# 1) Failure taxonomy
rows = []
for r in scores[~scores.execution_match].itertuples():
    q = questions[r.question_id]
    label, flags, evidence = taxonomy.label_failure(
        r.status, r.condition, r.category, q["question"], q["gold_sql"], r.generated_sql,
        scorers.rows_from_json(r.result_json), gold[r.question_id], r.n_rows)
    rows.append(dict(gen_key=r.gen_key, question_id=r.question_id, category=r.category, condition=r.condition,
                     seed=int(r.seed), status=r.status, label=label, flags=",".join(flags), evidence=evidence,
                     question=q["question"], generated_sql=r.generated_sql))
failures = pd.DataFrame(rows)
spark.createDataFrame(failures).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.failures")

review = failures.sample(n=min(25, len(failures)), random_state=7).assign(human_label="", agrees="")
spark.createDataFrame(review).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.failure_review")

taxo = failures.groupby(["condition", "label"]).size().reset_index(name="n")
display(taxo.pivot_table(index="label", columns="condition", values="n", fill_value=0))

# COMMAND ----------

# 2) Judge confusion matrix (judge verdict vs execution truth)
j = scores[scores.judge_correct.notna()].copy()
j["judge_correct"] = j.judge_correct.astype(bool)
conf = (j.assign(cell=j.apply(lambda r: ("judge_ok" if r.judge_correct else "judge_wrong") + "_" +
                                         ("exec_ok" if r.execution_match else "exec_wrong"), axis=1))
         .groupby(["condition", "cell"]).size().unstack(fill_value=0).reset_index())
for col in ["judge_ok_exec_ok", "judge_ok_exec_wrong", "judge_wrong_exec_ok", "judge_wrong_exec_wrong"]:
    if col not in conf:
        conf[col] = 0
conf["judge_precision"] = conf.judge_ok_exec_ok / (conf.judge_ok_exec_ok + conf.judge_ok_exec_wrong).clip(lower=1)
conf["judge_recall"] = conf.judge_ok_exec_ok / (conf.judge_ok_exec_ok + conf.judge_wrong_exec_ok).clip(lower=1)
conf["judge_false_negative_rate"] = conf.judge_wrong_exec_ok / (conf.judge_ok_exec_ok + conf.judge_wrong_exec_ok).clip(lower=1)
spark.createDataFrame(conf).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.judge_confusion")
display(conf)

# COMMAND ----------

# 3) Consistency: does the model give the same verdict across its 3 runs?
per_q = scores.groupby(["condition", "question_id"]).execution_match.agg(["sum", "count"]).reset_index()
per_q["pattern"] = per_q.apply(lambda r: "all_correct" if r["sum"] == r["count"] else
                               ("all_wrong" if r["sum"] == 0 else "mixed"), axis=1)
consistency = per_q.groupby(["condition", "pattern"]).size().unstack(fill_value=0).reset_index()
spark.createDataFrame(consistency).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.consistency")
display(consistency)

# COMMAND ----------

# 4) Cost vs accuracy (token estimates = characters / 4)
cost = scores.groupby("condition").agg(
    avg_input_tokens=("est_input_tokens", "mean"),
    avg_output_tokens=("response_chars", lambda s: (s.fillna(0) / 4).mean()),
    accuracy=("execution_match", "mean")).reset_index()
cost["input_tokens_per_correct_answer"] = cost.avg_input_tokens / cost.accuracy.clip(lower=1e-9)
spark.createDataFrame(cost).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.cost")
display(cost)

# COMMAND ----------

# 5) Figures
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.eval.artifacts")
FIG_DIR = f"/Volumes/{CATALOG}/eval/artifacts/figures"
os.makedirs(FIG_DIR, exist_ok=True)

summary = spark.table(f"{CATALOG}.eval.summary").toPandas()
wording = spark.table(f"{CATALOG}.eval.summary_by_wording").toPandas()
outcomes = (scores.groupby(["condition", "status"]).size() / scores.groupby("condition").size()).reset_index(name="share")

paths = [
    figures.fig_accuracy_by_category(summary, f"{FIG_DIR}/fig1_accuracy_by_category.png"),
    figures.fig_outcomes(outcomes, f"{FIG_DIR}/fig2_outcomes.png"),
    figures.fig_failure_taxonomy(taxo, f"{FIG_DIR}/fig3_failure_taxonomy.png"),
    figures.fig_judge(summary[summary.category == "ALL"], f"{FIG_DIR}/fig4_llm_judge.png"),
    figures.fig_wording(wording, f"{FIG_DIR}/fig5_wording_h3.png"),
    figures.fig_cost(cost, f"{FIG_DIR}/fig6_cost_vs_accuracy.png"),
]
print("\n".join(paths))

try:
    import mlflow
    user = spark.sql("SELECT current_user()").collect()[0][0]
    mlflow.set_experiment(f"/Users/{user}/lakehouse-sql-eval")
    with mlflow.start_run(run_name="analysis_figures"):
        for p in paths:
            mlflow.log_artifact(p, artifact_path="figures")
except Exception as e:  # noqa: BLE001
    print("MLflow artifact logging skipped:", str(e).splitlines()[0][:200])

# COMMAND ----------

# Headline numbers for the report
s = summary[summary.category == "ALL"].set_index("condition")
print("=== HEADLINE ===")
for c in figures.CONDITIONS:
    if c in s.index:
        print(f"{figures.NAMES[c]:32} accuracy {s.loc[c, 'accuracy']*100:5.1f}%  "
              f"[{s.loc[c, 'ci_low']*100:.0f}-{s.loc[c, 'ci_high']*100:.0f}]  "
              f"silent-wrong {s.loc[c, 'silent_wrong_rate']*100:4.1f}%")
print("\nTop failure types per condition:")
for c, grp in taxo.sort_values("n", ascending=False).groupby("condition"):
    print(f"  {c:14}", ", ".join(f"{r.label} ({r.n})" for r in grp.head(3).itertuples()))