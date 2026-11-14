"""Compare two SQL result sets: is the predicted answer the same as the gold answer?

Used in Phase 3 (gold SQL vs metric view) and Phase 5 (LLM SQL vs gold SQL).
Plain Python, no Spark, so it runs both in Databricks and in local pytest.
"""
import datetime as _dt
import math
from decimal import Decimal

REL_TOL = 0.005   # 0.5% relative tolerance for numbers
ABS_TOL = 0.01    # absolute tolerance (helps with values near zero)


def _norm(v):
    """Normalize one cell: numbers -> float, dates -> ISO string, text -> trimmed lowercase."""
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    if isinstance(v, _dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, _dt.date):
        return v.isoformat()
    return str(v).strip().lower()


def _as_float(v):
    if isinstance(v, float):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cell_equal(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL):
    if a is None or b is None:
        return a is None and b is None
    fa, fb = _as_float(a), _as_float(b)
    if fa is not None and fb is not None and (isinstance(a, float) or isinstance(b, float)):
        return math.isclose(fa, fb, rel_tol=rel_tol, abs_tol=abs_tol)  # handles 4 vs '4'
    return a == b


def _sort_key(row):
    # strings first (exact), then numbers rounded to 3 significant digits so near-equal values sort together
    key = []
    for v in row:
        if v is None:
            key.append((0, ""))
        elif isinstance(v, float):
            key.append((1, float(f"{v:.3g}")))
        else:
            key.append((2, v))
    return key


def normalize(rows):
    return [tuple(_norm(v) for v in row) for row in rows]


def results_match(gold_rows, pred_rows, ordered=False, rel_tol=REL_TOL, abs_tol=ABS_TOL):
    """Return (match: bool, reason: str)."""
    g, p = normalize(gold_rows), normalize(pred_rows)
    if len(g) != len(p):
        return False, f"row count {len(p)} != {len(g)}"
    if g and len(g[0]) != len(p[0]):
        return False, f"column count {len(p[0])} != {len(g[0])}"
    if not ordered:
        g, p = sorted(g, key=_sort_key), sorted(p, key=_sort_key)
    for i, (rg, rp) in enumerate(zip(g, p)):
        for j, (a, b) in enumerate(zip(rg, rp)):
            if not _cell_equal(a, b, rel_tol, abs_tol):
                return False, f"row {i} col {j}: {b!r} != {a!r}"
    return True, "match"