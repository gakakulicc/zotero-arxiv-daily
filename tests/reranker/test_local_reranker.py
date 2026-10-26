"""Tests for LocalReranker — requires sentence-transformers, marked slow."""

import pytest
import sys
from types import SimpleNamespace
import numpy as np

from zotero_arxiv_daily.reranker.local import LocalReranker
from zotero_arxiv_daily.reranker import local


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
def test_local_reranker_model_load_retries(config, monkeypatch, failures):
    config.executor.debug = True
    attempts = []
    waits = []
    expected = np.array([[0.75]])
    encoder = SimpleNamespace(
        encode=lambda texts, **kwargs: texts,
        similarity=lambda a, b: SimpleNamespace(numpy=lambda: expected),
    )

    def load_model(model, **kwargs):
        attempts.append(model)
        if len(attempts) <= failures:
            raise OSError("temporary download failure")
        return encoder

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=load_model))
    monkeypatch.setattr(local, "sleep", waits.append)
    reranker = LocalReranker(config)

    if failures == 3:
        with pytest.raises(RuntimeError, match="Failed to load model after 3 attempts") as exc:
            reranker.get_similarity_score(["hello"], ["world"])
        assert isinstance(exc.value.__cause__, OSError)
    else:
        assert np.array_equal(reranker.get_similarity_score(["hello"], ["world"]), expected)

    assert len(attempts) == min(failures + 1, 3)
    assert waits == [30, 60][:min(failures, 2)]


@pytest.mark.slow
def test_local_reranker(config):
    reranker = LocalReranker(config)
    score = reranker.get_similarity_score(["hello", "world"], ["ping"])
    assert score.shape == (2, 1)
