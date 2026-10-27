"""Ranking agreement metrics; agreement does not measure human relevance."""

import numpy as np


def _average_ranks(values):
    values = np.asarray(values)
    order = np.argsort(values, kind="stable")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        start = end
    return ranks


def ranking_agreement(left: list[dict], right: list[dict], k: int = 20) -> dict:
    left_ids, right_ids = [item["id"] for item in left], [item["id"] for item in right]
    if len(set(left_ids)) != len(left_ids) or set(left_ids) != set(right_ids) or len(left_ids) != len(right_ids):
        raise ValueError("Rankings must contain the same unique candidates")
    if k < 1 or not left:
        raise ValueError("A positive k and nonempty rankings are required")
    k = min(k, len(left))
    left_top, right_top = set(left_ids[:k]), set(right_ids[:k])
    left_scores = {item["id"]: item["score"] for item in left}
    right_scores = {item["id"]: item["score"] for item in right}
    x = _average_ranks([left_scores[key] for key in left_ids])
    y = _average_ranks([right_scores[key] for key in left_ids])
    correlation = float(np.corrcoef(x, y)[0, 1]) if len(x) > 1 and np.std(x) and np.std(y) else None
    return {
        "k": k, "overlap_count": len(left_top & right_top),
        "overlap_fraction": len(left_top & right_top) / k,
        "jaccard": len(left_top & right_top) / len(left_top | right_top),
        "spearman_all_candidates": correlation,
    }
