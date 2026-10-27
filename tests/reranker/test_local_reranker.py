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
    expected = np.array([[1.0]])
    encoder = SimpleNamespace(
        encode=lambda texts, **kwargs: np.array([[1.0, 0.0] for _ in texts]),
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
        assert np.allclose(reranker.get_similarity_score(["hello"], ["world"]), expected)

    assert len(attempts) == min(failures + 1, 3)
    assert waits == [30, 60][:min(failures, 2)]


@pytest.mark.slow
def test_local_reranker(config):
    reranker = LocalReranker(config)
    score = reranker.get_similarity_score(["hello", "world"], ["ping"])
    assert score.shape == (2, 1)


def test_embedding_cache_only_encodes_changed_texts(config, tmp_path, monkeypatch):
    config.reranker.local.cache_dir = str(tmp_path)
    calls = []
    features = {"alpha": [1, 0], "beta": [0, 1], "gamma": [1, 1]}

    def encode(texts, **kwargs):
        calls.append(texts)
        return np.array([features[text] for text in texts])

    monkeypatch.setattr(LocalReranker, "_load_encoder", lambda self: SimpleNamespace(encode=encode))
    first = LocalReranker(config).get_similarity_score(["alpha", "alpha"], ["beta"])
    assert np.allclose(first, [[0], [0]])
    assert calls == [["alpha", "beta"]]
    second = LocalReranker(config).get_similarity_score(["gamma", "alpha"], ["beta"])
    assert np.allclose(second, [[2 ** -0.5], [0]])
    assert calls[-1] == ["gamma"]
    monkeypatch.setattr(LocalReranker, "_load_encoder", lambda self: pytest.fail("Warm cache must not load the model"))
    assert np.allclose(LocalReranker(config).get_similarity_score(["gamma", "alpha"], ["beta"]), second)


@pytest.mark.parametrize("change", ["model", "max_seq_length", "encode_kwargs"])
def test_embedding_cache_invalidates_when_model_settings_change(config, tmp_path, monkeypatch, change):
    config.reranker.local.cache_dir = str(tmp_path)
    calls = []

    def encode(texts, **kwargs):
        calls.append(texts)
        return np.ones((len(texts), 2))

    monkeypatch.setattr(LocalReranker, "_load_encoder", lambda self: SimpleNamespace(encode=encode))
    LocalReranker(config).get_similarity_score(["a"], ["b"])
    if change == "model":
        config.reranker.local.model = "another-model"
    elif change == "max_seq_length":
        config.reranker.local.max_seq_length = 128
    else:
        config.reranker.local.encode_kwargs = {"normalize_embeddings": True}
    LocalReranker(config).get_similarity_score(["a"], ["b"])
    assert calls == [["a", "b"], ["a", "b"]]


def test_unwritable_cache_does_not_prevent_ranking(config, tmp_path, monkeypatch):
    cache_file = tmp_path / "not-a-directory"
    cache_file.write_text("occupied")
    config.reranker.local.cache_dir = str(cache_file)
    monkeypatch.setattr(LocalReranker, "_load_encoder", lambda self: SimpleNamespace(encode=lambda texts, **kw: np.ones((len(texts), 2))))
    assert np.allclose(LocalReranker(config).get_similarity_score(["a"], ["b"]), [[1]])


def test_zero_vectors_have_finite_similarity(config, monkeypatch):
    monkeypatch.setattr(LocalReranker, "_load_encoder", lambda self: SimpleNamespace(encode=lambda texts, **kw: np.zeros((len(texts), 2))))
    assert np.array_equal(LocalReranker(config).get_similarity_score(["a"], ["b"]), [[0]])
