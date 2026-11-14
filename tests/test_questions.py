"""Checks the benchmark file itself (runs locally, no Databricks needed)."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [json.loads(l) for l in open(ROOT / "src" / "questions" / "questions.jsonl")]
CATEGORIES = {"lookup", "aggregation", "business_definition", "time_fiscal"}


def test_sixty_questions_fifteen_per_category():
    assert len(QUESTIONS) == 60
    assert Counter(q["category"] for q in QUESTIONS) == {c: 15 for c in CATEGORIES}


def test_ids_unique():
    assert len({q["id"] for q in QUESTIONS}) == 60


def test_required_fields():
    for q in QUESTIONS:
        for field in ("id", "category", "question", "gold_sql", "mv_sql", "wording", "trap", "ordered"):
            assert field in q, f"{q['id']} missing {field}"
        assert q["gold_sql"].lstrip().upper().startswith("SELECT"), q["id"]
        assert q["wording"] in {"canonical", "synonym", "explicit"}, q["id"]


def test_gold_sql_never_uses_metric_view():
    # the answer key must be computed from raw gold tables, independently of the metric view
    for q in QUESTIONS:
        assert "MEASURE(" not in q["gold_sql"].upper(), q["id"]
        assert "metrics" not in q["gold_sql"], q["id"]


def test_business_and_time_questions_have_metric_view_sql():
    for q in QUESTIONS:
        if q["category"] in {"business_definition", "time_fiscal"}:
            assert q["mv_sql"] and "MEASURE(" in q["mv_sql"], q["id"]


def test_synonym_questions_exist_for_h3():
    assert sum(q["wording"] == "synonym" for q in QUESTIONS) >= 10