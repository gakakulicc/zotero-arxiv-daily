"""Score a completed blind review; missing labels must never count as irrelevant."""

import argparse
import csv
import json
import math
from pathlib import Path


def evaluate(comparison, rows):
    selected = comparison["top20"]
    expected = {paper["id"] for papers in selected.values() for paper in papers}
    labels = {}
    for row in rows:
        key = row["paper_id"]
        if key in labels:
            raise ValueError(f"Duplicate review: {key}")
        if row.get("relevance_0_1_2") not in {"0", "1", "2"}:
            raise ValueError(f"Review requires a 0, 1 or 2 label: {key}")
        labels[key] = int(row["relevance_0_1_2"])
    if set(labels) != expected:
        raise ValueError("Review must label exactly the union of all reported top-20 selections")

    def dcg(grades):
        return sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))

    results = {}
    ideal = sorted(labels.values(), reverse=True)
    for profile, papers in selected.items():
        grades = [labels[paper["id"]] for paper in papers]
        if not grades:
            raise ValueError("Cannot evaluate empty selections")
        denominator = dcg(ideal[:len(grades)])
        results[profile] = {
            "k": len(grades),
            "directly_relevant_count": grades.count(2),
            "partly_relevant_count": grades.count(1),
            "irrelevant_count": grades.count(0),
            "precision_direct": grades.count(2) / len(grades),
            "precision_including_supporting": sum(grade >= 1 for grade in grades) / len(grades),
            "ndcg_within_reviewed_union": dcg(grades) / denominator if denominator else None,
        }
    return {
        "snapshot_sha256": comparison["snapshot_sha256"],
        "reviewed_papers": len(labels),
        "scope": "Subjective relevance labels for the selected union only; not full-pool recall or general accuracy",
        "profiles": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    with args.review.open(encoding="utf-8-sig", newline="") as stream:
        results = evaluate(json.loads(args.comparison.read_text(encoding="utf-8-sig")), list(csv.DictReader(stream)))
    print(json.dumps(results, ensure_ascii=False, indent=2))
