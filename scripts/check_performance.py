"""Measure a realistic embedding workload on the CI CPU, using public synthetic text."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
from omegaconf import OmegaConf

from zotero_arxiv_daily.reranker.local import LocalReranker


def main():
    config = OmegaConf.load(Path(__file__).resolve().parents[1] / "config" / "base.yaml")
    # Distinct abstracts of realistic length; no user library or credentials are used.
    paragraph = ("We study scientific document retrieval using compact neural representations. "
                 "Experiments compare relevance, generalization, and computational cost across several datasets. "
                 "Our method combines semantic similarity with recent research interests and evaluates robust baselines. ")
    candidates = [f"Candidate experiment {i}. " + paragraph * 5 for i in range(350)]
    corpus = [f"Library experiment {i}. " + paragraph * 5 for i in range(456)]
    with TemporaryDirectory() as directory:
        config.reranker.local.cache_dir = directory
        started = perf_counter()
        cold_scores = LocalReranker(config).get_similarity_score(candidates, corpus)
        cold = perf_counter() - started
        started = perf_counter()
        warm_scores = LocalReranker(config).get_similarity_score(candidates, corpus)
        warm = perf_counter() - started
        assert cold_scores.shape == (350, 456)
        assert np.isfinite(cold_scores).all()
        assert np.allclose(cold_scores, warm_scores, atol=1e-6)
        result = {"embedding_model": config.reranker.local.model, "candidates": 350, "corpus": 456,
                  "cold_seconds_including_model_load": round(cold, 2), "warm_cache_seconds": round(warm, 2)}
        print(json.dumps(result, indent=2))
        print("::notice title=CPU embedding benchmark::" + json.dumps(result))
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary_path, "a", encoding="utf-8") as output:
                output.write("### CPU embedding benchmark\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n")


if __name__ == "__main__":
    main()
