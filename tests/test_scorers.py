import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "evaluate"))
import scorers  # noqa: E402
import stats  # noqa: E402


# --- safety -----------------------------------------------------------------
def test_only_read_only_sql_is_executed():
    assert scorers.is_safe_select("SELECT 1")
    assert scorers.is_safe_select("WITH x AS (SELECT 1) SELECT * FROM x;")
    assert not scorers.is_safe_select("DROP TABLE workspace.gold.fact_orders")
    assert not scorers.is_safe_select("SELECT 1; DELETE FROM t")
    assert not scorers.is_safe_select("UPDATE t SET a = 1")
    assert not scorers.is_safe_select(None)


# --- serialisation ------------------------------------------------------------
def test_json_round_trip_keeps_values_comparable():
    rows = [(Decimal("7316265.52"), dt.date(2025, 1, 31), "Europe", None, 3)]
    back = scorers.rows_from_json(scorers.rows_to_json(rows))
    assert back == [(7316265.52, "2025-01-31", "Europe", None, 3)]
    assert scorers.execution_match(rows, back)[0]


# --- matching -----------------------------------------------------------------
def test_extra_column_is_allowed():
    gold = [("Europe",)]
    pred = [("Europe", 123456.0)]
    assert scorers.execution_match(gold, pred)[0]


def test_column_order_does_not_matter():
    gold = [("web", 10.0), ("store", 2.0)]
    pred = [(2.0, "store"), (10.0, "web")]
    assert scorers.execution_match(gold, pred)[0]


def test_wrong_number_is_wrong_even_with_extra_columns():
    gold = [(7316265.52,)]
    pred = [(7852428.27, 100)]       # gross instead of net
    assert not scorers.execution_match(gold, pred)[0]


def test_row_count_uses_true_count_when_truncated():
    assert not scorers.execution_match([(1,)], [(1,)], pred_n_rows=5000)[0]


# --- classification ----------------------------------------------------------
def test_classify_all_statuses():
    gold = [(100.0,)]
    assert scorers.classify(None, "ok", [], gold, False)[0] == "no_sql"
    assert scorers.classify("SELECT", "error: bad column", [], gold, False)[0] == "error"
    assert scorers.classify("SELECT", "ok", [], gold, False)[0] == "empty"
    assert scorers.classify("SELECT", "ok", [(None,)], gold, False)[0] == "empty"
    assert scorers.classify("SELECT", "ok", [(100.2,)], gold, False)[0] == "correct"
    assert scorers.classify("SELECT", "ok", [(150.0,)], gold, False)[0] == "silent_wrong"


# --- judge parsing ------------------------------------------------------------
def test_parse_verdict():
    assert scorers.parse_verdict("VERDICT: CORRECT\nREASON: fine") is True
    assert scorers.parse_verdict("**VERDICT:** INCORRECT\nREASON: misses refunds") is False
    assert scorers.parse_verdict("Correct. The query...") is True
    assert scorers.parse_verdict("I think so") is None
    assert scorers.parse_verdict(None) is None


# --- statistics -------------------------------------------------------------
def test_bootstrap_clusters_by_question():
    # q1 always right, q2 always wrong, 3 seeds each -> mean 0.5 and a wide CI
    q = ["q1"] * 3 + ["q2"] * 3
    v = [1, 1, 1, 0, 0, 0]
    mean, lo, hi = stats.bootstrap_ci(q, v)
    assert mean == 0.5 and lo <= 0.5 <= hi and lo < hi


def test_paired_difference():
    qa, va = ["q1", "q2", "q3"], [1, 1, 1]
    qb, vb = ["q1", "q2", "q3"], [0, 1, 0]
    d, lo, hi = stats.paired_diff_ci(qa, va, qb, vb)
    assert abs(d - 2 / 3) < 1e-9 and lo <= d <= hi