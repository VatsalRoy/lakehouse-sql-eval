# Databricks notebook source
# MAGIC %md
# MAGIC # Score everything and log to MLflow
# MAGIC 1. Score each generation: correct / silent_wrong / empty / error  -> `eval.scores`
# MAGIC 2. `mlflow.genai.evaluate` (answer-sheet mode): one MLflow run per condition x seed, with custom scorers
# MAGIC 3. Summary with 95% bootstrap CIs (resampling questions) -> `eval.summary`, `eval.paired_diffs`, `eval.summary_by_wording`

# COMMAND ----------

# MAGIC %pip install --quiet --upgrade "mlflow[databricks]>=3.1.0"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("repo_root", "")
dbutils.widgets.text("llm_endpoint", "")
dbutils.widgets.text("judge_endpoint", "")

CATALOG = dbutils.widgets.get("catalog")
REPO_ROOT = dbutils.widgets.get("repo_root")
ENDPOINT = dbutils.widgets.get("llm_endpoint")
JUDGE = dbutils.widgets.get("judge_endpoint") or ENDPOINT

import json
import os
import sys

sys.path.insert(0, os.path.join(REPO_ROOT, "src", "evaluate"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "generate"))
import prompts  # noqa: E402
import scorers  # noqa: E402
import stats  # noqa: E402

questions = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(REPO_ROOT, "src", "questions", "questions.jsonl"))}
gold = {r.question_id: scorers.rows_from_json(r.gold_json) for r in spark.table(f"{CATALOG}.eval.gold_results").collect()}

# COMMAND ----------

# 1) Score every generation
data = spark.sql(f"""
  SELECT g.gen_key, g.question_id, g.category, g.wording, g.condition, g.seed, g.est_input_tokens, g.generated_sql,
         e.exec_status, e.n_rows, e.result_json, e.exec_ms,
         j.judge_correct, j.judge_response
  FROM {CATALOG}.eval.generations g
  LEFT JOIN {CATALOG}.eval.executions e USING (gen_key)
  LEFT JOIN (SELECT * FROM {CATALOG}.eval.judgments
             WHERE judge_endpoint = '{JUDGE}' AND judge_version = '{prompts.JUDGE_VERSION}') j USING (gen_key)
  WHERE g.endpoint = '{ENDPOINT}'""").collect()

scored = []
for d in data:
    q = questions[d.question_id]
    pred = scorers.rows_from_json(d.result_json)
    status, match, detail = scorers.classify(d.generated_sql, d.exec_status or "no_sql", pred,
                                             gold[d.question_id], q["ordered"], d.n_rows)
    agrees = None if d.judge_correct is None else (d.judge_correct == match)
    scored.append(dict(
        gen_key=d.gen_key, question_id=d.question_id, category=d.category, wording=d.wording,
        condition=d.condition, seed=d.seed, est_input_tokens=d.est_input_tokens,
        generated_sql=d.generated_sql, exec_status=d.exec_status, n_rows=d.n_rows,
        status=status, execution_match=match, silent_wrong=(status == "silent_wrong"), match_detail=detail,
        judge_correct=d.judge_correct, judge_agrees=agrees,
        pred_preview=(d.result_json or "")[:300], gold_preview=json.dumps(gold[d.question_id][:3], default=str)[:300],
    ))

SCORE_COLS = ["gen_key", "question_id", "category", "wording", "condition", "seed", "est_input_tokens",
              "generated_sql", "exec_status", "n_rows", "status", "execution_match", "silent_wrong",
              "match_detail", "judge_correct", "judge_agrees", "pred_preview", "gold_preview"]
SCORE_SCHEMA = ("gen_key STRING, question_id STRING, category STRING, wording STRING, condition STRING, seed INT, "
                "est_input_tokens INT, generated_sql STRING, exec_status STRING, n_rows INT, status STRING, "
                "execution_match BOOLEAN, silent_wrong BOOLEAN, match_detail STRING, judge_correct BOOLEAN, "
                "judge_agrees BOOLEAN, pred_preview STRING, gold_preview STRING")
spark.createDataFrame([tuple(s[c] for c in SCORE_COLS) for s in scored], SCORE_SCHEMA) \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.eval.scores")
print(f"Scored {len(scored)} generations -> {CATALOG}.eval.scores")

# COMMAND ----------

# 2) MLflow GenAI evaluation (answer-sheet mode: outputs are pre-computed, scorers re-check them)
import mlflow
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

user = spark.sql("SELECT current_user()").collect()[0][0]
mlflow.set_experiment(f"/Users/{user}/lakehouse-sql-eval")


@scorer
def execution_match(outputs, expectations) -> Feedback:
    status, match, detail = scorers.classify(outputs["sql"], outputs["exec_status"], [tuple(r) for r in outputs["result"]],
                                             [tuple(r) for r in expectations["gold_result"]],
                                             expectations["ordered"], outputs["n_rows"])
    return Feedback(value=match, rationale=f"{status}: {detail}")


@scorer
def silent_wrong(outputs, expectations) -> bool:
    status, _, _ = scorers.classify(outputs["sql"], outputs["exec_status"], [tuple(r) for r in outputs["result"]],
                                    [tuple(r) for r in expectations["gold_result"]],
                                    expectations["ordered"], outputs["n_rows"])
    return status == "silent_wrong"


@scorer
def runs_without_error(outputs) -> bool:
    return outputs["exec_status"] == "ok"


@scorer
def llm_judge_says_correct(outputs) -> Feedback:
    return Feedback(value=bool(outputs["judge_correct"]), rationale=(outputs["judge_response"] or "")[:500])


@scorer
def judge_agrees_with_execution(outputs, expectations) -> bool:
    status, match, _ = scorers.classify(outputs["sql"], outputs["exec_status"], [tuple(r) for r in outputs["result"]],
                                        [tuple(r) for r in expectations["gold_result"]],
                                        expectations["ordered"], outputs["n_rows"])
    return bool(outputs["judge_correct"]) == match


judge_text = {d.gen_key: d.judge_response for d in data}
result_json = {d.gen_key: d.result_json for d in data}
mlflow_ok = True
for cond in prompts.CONDITIONS:
    for seed in sorted({s["seed"] for s in scored}):
        batch = [s for s in scored if s["condition"] == cond and s["seed"] == seed]
        if not batch:
            continue
        eval_data = [{
            "inputs": {"question_id": s["question_id"], "question": questions[s["question_id"]]["question"],
                       "category": s["category"], "wording": s["wording"]},
            "outputs": {"sql": s["generated_sql"], "exec_status": s["exec_status"] or "no_sql", "n_rows": s["n_rows"],
                        "result": scorers.rows_from_json(result_json[s["gen_key"]])[:50],
                        "judge_correct": s["judge_correct"], "judge_response": judge_text.get(s["gen_key"])},
            "expectations": {"gold_result": gold[s["question_id"]], "ordered": questions[s["question_id"]]["ordered"]},
        } for s in batch]
        try:
            with mlflow.start_run(run_name=f"{cond}_seed{seed}"):
                mlflow.log_params({"condition": cond, "seed": seed, "llm_endpoint": ENDPOINT,
                                   "judge_endpoint": JUDGE, "template_version": prompts.TEMPLATE_VERSION})
                mlflow.genai.evaluate(data=eval_data, scorers=[execution_match, silent_wrong, runs_without_error,
                                                               llm_judge_says_correct, judge_agrees_with_execution])
            print(f"MLflow run logged: {cond} seed {seed}")
        except Exception as e:  # noqa: BLE001
            mlflow_ok = False
            print(f"MLflow logging failed for {cond} seed {seed}: {str(e).splitlines()[0][:200]}")

# COMMAND ----------

# 3) Summary tables with 95% bootstrap CIs (clustered by question)
def summarize(rows):
    q = [r["question_id"] for r in rows]
    acc, lo, hi = stats.bootstrap_ci(q, [r["execution_match"] for r in rows])
    n = len(rows)
    failures = [r for r in rows if not r["execution_match"]]
    judged = [r for r in rows if r["judge_correct"] is not None]
    judged_wrong = [r for r in judged if not r["execution_match"]]
    return dict(
        n_questions=len(set(q)), n_generations=n,
        accuracy=acc, ci_low=lo, ci_high=hi,
        silent_wrong_rate=sum(r["status"] == "silent_wrong" for r in rows) / n,
        error_rate=sum(r["status"] == "error" for r in rows) / n,
        empty_rate=sum(r["status"] == "empty" for r in rows) / n,
        silent_share_of_failures=(sum(r["status"] == "silent_wrong" for r in failures) / len(failures)) if failures else None,
        judge_says_correct_rate=(sum(bool(r["judge_correct"]) for r in judged) / len(judged)) if judged else None,
        judge_agreement=(sum(bool(r["judge_agrees"]) for r in judged) / len(judged)) if judged else None,
        judge_false_positive_rate=(sum(bool(r["judge_correct"]) for r in judged_wrong) / len(judged_wrong)) if judged_wrong else None,
        avg_input_tokens=sum(r["est_input_tokens"] or 0 for r in rows) / n,
    )


summary = []
for cond in prompts.CONDITIONS:
    for cat in ["ALL", "lookup", "aggregation", "business_definition", "time_fiscal"]:
        rows = [s for s in scored if s["condition"] == cond and (cat == "ALL" or s["category"] == cat)]
        if rows:
            summary.append(dict(condition=cond, category=cat, **summarize(rows)))

by_wording = []
for cond in prompts.CONDITIONS:
    for w in ["canonical", "synonym", "explicit"]:
        rows = [s for s in scored if s["condition"] == cond and s["wording"] == w]
        if rows:
            acc, lo, hi = stats.bootstrap_ci([r["question_id"] for r in rows], [r["execution_match"] for r in rows])
            by_wording.append(dict(condition=cond, wording=w, n_questions=len({r["question_id"] for r in rows}),
                                   accuracy=acc, ci_low=lo, ci_high=hi))

pairs = [("C_metric_view", "A_raw"), ("C_metric_view", "B_comments"), ("B_comments", "A_raw"), ("C_metric_view", "C_nosyn")]
diffs = []
for a, b in pairs:
    for cat in ["ALL", "lookup", "aggregation", "business_definition", "time_fiscal"]:
        ra = [s for s in scored if s["condition"] == a and (cat == "ALL" or s["category"] == cat)]
        rb = [s for s in scored if s["condition"] == b and (cat == "ALL" or s["category"] == cat)]
        if ra and rb:
            d, lo, hi = stats.paired_diff_ci([r["question_id"] for r in ra], [r["execution_match"] for r in ra],
                                             [r["question_id"] for r in rb], [r["execution_match"] for r in rb])
            diffs.append(dict(comparison=f"{a} - {b}", category=cat, diff=d, ci_low=lo, ci_high=hi,
                              significant=(lo > 0 or hi < 0)))

import pandas as pd

for name, rows in [("summary", summary), ("summary_by_wording", by_wording), ("paired_diffs", diffs)]:
    spark.createDataFrame(pd.DataFrame(rows)).write.mode("overwrite").option("overwriteSchema", "true") \
        .saveAsTable(f"{CATALOG}.eval.{name}")

# headline numbers into one MLflow run for easy comparison later
try:
    with mlflow.start_run(run_name="summary"):
        for s in summary:
            if s["category"] == "ALL":
                mlflow.log_metric(f"{s['condition']}_accuracy", s["accuracy"])
                mlflow.log_metric(f"{s['condition']}_silent_wrong_rate", s["silent_wrong_rate"])
                if s["judge_agreement"] is not None:
                    mlflow.log_metric(f"{s['condition']}_judge_agreement", s["judge_agreement"])
        mlflow.log_table(pd.DataFrame(summary), "summary.json")
        mlflow.log_table(pd.DataFrame(diffs), "paired_diffs.json")
except Exception as e:  # noqa: BLE001
    print("Summary MLflow run skipped:", str(e).splitlines()[0][:200])

display(spark.sql(f"""
  SELECT condition, category, ROUND(accuracy, 3) AS accuracy, ROUND(ci_low, 3) AS ci_low, ROUND(ci_high, 3) AS ci_high,
         ROUND(silent_wrong_rate, 3) AS silent_wrong, ROUND(judge_agreement, 3) AS judge_agreement
  FROM {CATALOG}.eval.summary ORDER BY category, condition"""))
display(spark.table(f"{CATALOG}.eval.paired_diffs"))