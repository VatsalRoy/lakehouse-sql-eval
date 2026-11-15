import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "generate"))
import prompts  # noqa: E402

SCHEMA = {
    "fact_orders": [("order_id", "BIGINT"), ("status", "STRING"), ("order_total_usd", "DECIMAL(18,2)")],
    "dim_customer": [("customer_id", "BIGINT"), ("is_test_account", "BOOLEAN")],
}
COMMENTS = yaml.safe_load(open(ROOT / "src" / "catalog" / "column_comments.yaml"))
MVS = {p.stem: p.read_text().replace("{{catalog}}", "workspace") for p in sorted((ROOT / "src" / "semantic").glob("*.yaml"))}


def ctx(cond):
    return prompts.build_context(cond, SCHEMA, "workspace", COMMENTS, MVS)


def test_condition_a_has_no_comments_or_metric_views():
    c = ctx("A_raw")
    assert "TABLE workspace.gold.fact_orders" in c and "--" not in c and "MEASURE" not in c


def test_condition_b_adds_comments_only():
    c = ctx("B_comments")
    assert "-- Order status" in c and "MEASURE" not in c and "net_revenue" not in c


def test_condition_c_has_metric_views_and_synonyms():
    c = ctx("C_metric_view")
    assert "METRIC VIEW workspace.gold.sales_metrics" in c and "MEASURE(" in c and "money we made" in c


def test_condition_c_nosyn_strips_synonyms_but_keeps_logic():
    c = ctx("C_nosyn")
    assert "sales_metrics_nosyn" in c and "synonyms" not in c and "money we made" not in c
    assert "net_revenue" in c and "MEASURE(gross_revenue) - MEASURE(refunds)" in c


def test_only_question_placeholder_left():
    t = prompts.condition_template(ctx("A_raw"))
    assert "{{context}}" not in t and "{{question}}" in t
    assert prompts.render(t, "What was revenue?").endswith("Question: What was revenue?\n")


def test_extract_sql_variants():
    assert prompts.extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert prompts.extract_sql("Here you go:\n```\nSELECT 2\n```") == "SELECT 2"
    assert prompts.extract_sql("draft ```sql SELECT 0``` final ```sql\nWITH x AS (SELECT 1) SELECT * FROM x```").startswith("WITH x")
    assert prompts.extract_sql("Sure! SELECT 3") == "SELECT 3"
    assert prompts.extract_sql(None) is None


def test_extract_sql_from_reasoning_blocks():
    raw = '[{"type": "reasoning", "summary": [{"text": "think ```sql SELECT 0```"}]}, {"type": "text", "text": "```sql\\nSELECT 42\\n```"}]'
    assert prompts.extract_sql(raw) == "SELECT 42"



def test_judge_prompt_contains_everything():
    p = prompts.render_judge(ctx("B_comments"), "What was revenue?", "SELECT 1")
    assert "SELECT 1" in p and "What was revenue?" in p and "-- Order status" in p
    assert "{{" not in p and "VERDICT: CORRECT" in p