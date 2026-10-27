import pytest

from scripts.review_rankings import evaluate


def test_missing_review_cannot_be_reported_as_irrelevant():
    data = {"snapshot_sha256": "snapshot", "top20": {"left": [{"id": "a"}], "right": [{"id": "b"}]}}
    with pytest.raises(ValueError, match="exactly the union"):
        evaluate(data, [{"paper_id": "a", "relevance_0_1_2": "2"}])
    with pytest.raises(ValueError, match="0, 1 or 2"):
        evaluate(data, [{"paper_id": "a", "relevance_0_1_2": ""}])


def test_relevance_quality_is_separate_from_selection_overlap():
    data = {"snapshot_sha256": "snapshot", "top20": {
        "better": [{"id": "a"}, {"id": "b"}], "worse": [{"id": "b"}, {"id": "c"}]}}
    rows = [{"paper_id": key, "relevance_0_1_2": grade} for key, grade in [("a", "2"), ("b", "1"), ("c", "0")]]
    result = evaluate(data, rows)["profiles"]
    assert result["better"]["precision_direct"] == .5
    assert result["better"]["ndcg_within_reviewed_union"] == pytest.approx(1)
    assert result["worse"]["precision_direct"] == 0
    assert result["worse"]["precision_including_supporting"] == .5
    assert result["worse"]["ndcg_within_reviewed_union"] < 1
