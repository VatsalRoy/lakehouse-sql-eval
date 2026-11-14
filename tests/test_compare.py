import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "evaluate"))
from compare import results_match  # noqa: E402


def test_exact_number():
    assert results_match([(100.0,)], [(100,)])[0]


def test_within_tolerance():
    assert results_match([(Decimal("7316265.52"),)], [(7340000.0,)])[0]      # 0.32% off


def test_outside_tolerance():
    assert not results_match([(7316265.52,)], [(7852428.27,)])[0]           # gross vs net


def test_unordered_rows():
    gold = [("Europe", 5.0), ("North America", 9.0)]
    pred = [("North America", 9.0), ("Europe", 5.0)]
    assert results_match(gold, pred)[0]


def test_ordered_rows_must_match_order():
    gold = [(1, 10.0), (2, 20.0)]
    pred = [(2, 20.0), (1, 10.0)]
    assert not results_match(gold, pred, ordered=True)[0]


def test_text_case_and_whitespace():
    assert results_match([("North America",)], [(" north america ",)])[0]


def test_dates():
    assert results_match([(dt.date(2023, 7, 5),)], [(dt.date(2023, 7, 5),)])[0]


def test_row_count_mismatch():
    ok, reason = results_match([(1,), (2,)], [(1,)])
    assert not ok and "row count" in reason


def test_null_handling():
    assert results_match([(None,)], [(None,)])[0]
    assert not results_match([(None,)], [(0.0,)])[0]


def test_number_vs_numeric_string():
    assert results_match([(4,)], [("4",)])[0]