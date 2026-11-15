"""Scoring logic for generated SQL (plain Python: runs in Databricks and in local pytest).

Every generation gets exactly one status:
  correct       - ran, and the result matches the gold answer
  silent_wrong  - ran, returned non-empty rows, but the answer is WRONG   <- the dangerous one (H2)
  empty         - ran but returned no rows (or only NULLs)
  error         - failed to run (syntax, unknown column, timeout, blocked statement)
  no_sql        - the model produced no SQL
"""
import datetime as _dt
import itertools
import json
import re
from decimal import Decimal

from compare import results_match

MAX_STORED_ROWS = 200
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|OPTIMIZE|VACUUM)\b", re.I)


# ----------------------------------------------------------------------------- safety
def is_safe_select(sql: str | None) -> bool:
    """Only run read-only single statements. LLM output is untrusted code."""
    if not sql:
        return False
    s = sql.strip().rstrip(";")
    if ";" in s:
        return False
    if not re.match(r"^\s*(WITH|SELECT|\()", s, re.I):
        return False
    return not _FORBIDDEN.search(s)


# ----------------------------------------------------------------------------- (de)serialising results
def _cell(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, _dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v)


def rows_to_json(rows, limit=MAX_STORED_ROWS) -> str:
    return json.dumps([[_cell(v) for v in r] for r in list(rows)[:limit]])


def rows_from_json(s: str | None):
    return [tuple(r) for r in json.loads(s)] if s else []


# ----------------------------------------------------------------------------- matching
def execution_match(gold_rows, pred_rows, ordered=False, pred_n_rows=None):
    """Does the predicted result answer the question the same way as gold?

    Lenient on PRESENTATION, strict on VALUES:
      - extra columns are allowed (e.g. returning region AND revenue when only region was asked)
      - column order does not matter
      - numbers within 0.5%; text case/whitespace ignored; row order ignored unless the question needs it
    Returns (match: bool, how: str).
    """
    if pred_n_rows is not None and pred_n_rows != len(gold_rows):
        return False, f"row count {pred_n_rows} != {len(gold_rows)}"
    ok, why = results_match(gold_rows, pred_rows, ordered=ordered)
    if ok:
        return True, "exact"
    if not gold_rows or not pred_rows or len(gold_rows) != len(pred_rows):
        return False, why
    k, n = len(gold_rows[0]), len(pred_rows[0])
    if n < k or n > 8:
        return False, why
    for cols in itertools.permutations(range(n), k):          # try every way of picking k columns
        proj = [tuple(r[c] for c in cols) for r in pred_rows]
        if results_match(gold_rows, proj, ordered=ordered)[0]:
            return True, f"columns {list(cols)}"
    return False, why


def is_empty(rows) -> bool:
    return len(rows) == 0 or all(all(v is None for v in r) for r in rows)


def classify(generated_sql, exec_status, pred_rows, gold_rows, ordered, pred_n_rows=None):
    """Return (status, match: bool, detail)."""
    if not generated_sql:
        return "no_sql", False, "no SQL produced"
    if exec_status != "ok":
        return "error", False, exec_status
    if is_empty(pred_rows):
        return "empty", False, "no rows / all NULL"
    match, how = execution_match(gold_rows, pred_rows, ordered, pred_n_rows)
    return ("correct" if match else "silent_wrong"), match, how


# ----------------------------------------------------------------------------- LLM judge
_VERDICT = re.compile(r"VERDICT\s*:\s*\**\s*(CORRECT|INCORRECT)", re.I)


def parse_verdict(text: str | None):
    """True / False / None (unparseable)."""
    if not text:
        return None
    m = _VERDICT.search(text)
    if m:
        return m.group(1).upper() == "CORRECT"
    first = text.strip().split()[0].strip("*:.").upper() if text.strip() else ""
    if first in ("CORRECT", "INCORRECT"):
        return first == "CORRECT"
    return None