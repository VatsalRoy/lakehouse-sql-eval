"""Bootstrap confidence intervals, resampling QUESTIONS (not individual generations).

Why questions: the 3 seeds of one question are not independent evidence, so we first average
seeds per question, then resample the 60 (or 15 per category) questions with replacement.
"""
import numpy as np


def per_question_means(question_ids, values):
    """Average the seeds of each question. Returns (ids, means) in a stable order."""
    acc = {}
    for q, v in zip(question_ids, values):
        acc.setdefault(q, []).append(float(v))
    ids = sorted(acc)
    return ids, np.array([np.mean(acc[q]) for q in ids])


def bootstrap_ci(question_ids, values, n_boot=2000, alpha=0.05, seed=0):
    """Mean and (1 - alpha) percentile CI of a per-generation 0/1 score, clustered by question."""
    _, m = per_question_means(question_ids, values)
    if len(m) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = m[rng.integers(0, len(m), size=(n_boot, len(m)))].mean(axis=1)
    return float(m.mean()), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))


def paired_diff_ci(qids_a, vals_a, qids_b, vals_b, n_boot=2000, alpha=0.05, seed=0):
    """Mean difference (A - B) over the SAME questions, with a paired bootstrap CI."""
    ida, ma = per_question_means(qids_a, vals_a)
    idb, mb = per_question_means(qids_b, vals_b)
    common = sorted(set(ida) & set(idb))
    da, db = dict(zip(ida, ma)), dict(zip(idb, mb))
    d = np.array([da[q] - db[q] for q in common])
    if len(d) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(axis=1)
    return float(d.mean()), float(np.quantile(boots, alpha / 2)), float(np.quantile(boots, 1 - alpha / 2))