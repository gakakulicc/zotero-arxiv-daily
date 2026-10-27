import json

import pytest

from zotero_arxiv_daily.comparison import ranking_agreement


def ranking(ids, scores=None):
    scores = scores or list(range(len(ids), 0, -1))
    return [{"id": str(key), "score": score, "title": f"Public paper {key}", "url": f"https://arxiv.org/abs/{key}"}
            for key, score in zip(ids, scores)]


def test_identical_selections_have_full_agreement():
    result = ranking_agreement(ranking([1, 2, 3]), ranking([1, 2, 3]), 2)
    assert result["overlap_count"] == 2
    assert result["jaccard"] == 1
    assert result["spearman_all_candidates"] == pytest.approx(1)


def test_reversed_rankings_have_negative_correlation():
    result = ranking_agreement(ranking([1, 2, 3, 4]), ranking([4, 3, 2, 1]), 2)
    assert result["overlap_count"] == 0
    assert result["spearman_all_candidates"] == pytest.approx(-1)


def test_correlation_handles_tied_scores():
    result = ranking_agreement(ranking([1, 2, 3], [3, 3, 1]), ranking([2, 1, 3], [3, 3, 1]))
    assert result["spearman_all_candidates"] == pytest.approx(1)
    assert result["k"] == 3


@pytest.mark.parametrize("right", [ranking([1, 1]), ranking([1, 3])])
def test_different_candidate_pools_are_rejected(right):
    with pytest.raises(ValueError, match="same unique candidates"):
        ranking_agreement(ranking([1, 2]), right)


def test_public_report_does_not_expose_library_contents(tmp_path, monkeypatch):
    from scripts.compare_rankings import report

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    snapshot = {"captured_at": "2026-10-27T00:00:00Z", "corpus": [{"abstract": "PRIVATE_LIBRARY_CONTENT"}],
                "candidates": [{"title": "public"}] * 3}
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot))
    for profile, ids in [("gist512", [1, 2, 3]), ("jina512", [3, 2, 1]), ("jina8192", [2, 3, 1])]:
        (tmp_path / f"{profile}.json").write_text(json.dumps({"profile": profile, "ranking": ranking(ids)}))
    report(tmp_path)
    files = list((tmp_path / "report").iterdir())
    assert len(files) == 3
    assert all("PRIVATE_LIBRARY_CONTENT" not in path.read_text(encoding="utf-8-sig") for path in files)
    assert "relevance_0_1_2" in (tmp_path / "report" / "blind-review.csv").read_text(encoding="utf-8-sig")
