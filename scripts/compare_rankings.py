"""Compare real paper selections on one frozen library/feed snapshot; never send email."""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
from time import perf_counter

from hydra import compose, initialize_config_dir
from huggingface_hub import model_info
from loguru import logger
import numpy as np
from omegaconf import OmegaConf

from zotero_arxiv_daily.compat import apply_legacy_environment
from zotero_arxiv_daily.comparison import ranking_agreement
from zotero_arxiv_daily.executor import Executor, normalize_path_patterns
from zotero_arxiv_daily.protocol import Paper, CorpusPaper
from zotero_arxiv_daily.reranker.base import BaseReranker
from zotero_arxiv_daily.reranker.local import LocalReranker
from zotero_arxiv_daily.retriever import get_retriever_cls

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"gist": "avsolatorio/GIST-small-Embedding-v0",
          "jina": "jinaai/jina-embeddings-v5-text-nano-retrieval"}
PROFILES = ("gist512", "jina512", "jina8192")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(directory):
    with initialize_config_dir(config_dir=str(ROOT / "config"), version_base=None):
        config = compose(config_name="default")
    apply_legacy_environment(config)
    config.executor.debug = False  # Compare the whole candidate pool, not the manual test's first ten.
    # Reuse production corpus/filter logic without creating an LLM client or touching SMTP settings.
    executor = Executor.__new__(Executor)
    executor.config = config
    executor.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
    executor.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
    logger.disable("zotero_arxiv_daily.executor")  # Avoid printing private library titles or collection paths.
    try:
        corpus = executor.filter_corpus(executor.fetch_zotero_corpus())
    finally:
        logger.enable("zotero_arxiv_daily.executor")
    corpus = sorted(corpus, key=lambda paper: paper.added_date, reverse=True)
    papers = []
    for source in config.executor.source:
        papers.extend(get_retriever_cls(source)(config).retrieve_papers())
    papers = list({paper.source + ":" + paper.url: paper for paper in papers}.values())
    if not corpus or not papers:
        raise RuntimeError("The real library or current feeds are empty; no comparison can be made. Retry after the RSS update.")
    revisions = {name: model_info(repo).sha for name, repo in MODELS.items()}
    data = {"captured_at": datetime.now(timezone.utc).isoformat(),
            "corpus": [{"abstract": paper.abstract, "added_date": paper.added_date.isoformat()} for paper in corpus],
            "candidates": [asdict(paper) for paper in papers], "model_revisions": revisions,
            "library_abstracts_containing_cjk": sum(any('\u4e00' <= char <= '\u9fff' for char in paper.abstract) for paper in corpus)}
    save(directory / "snapshot.json", data)
    print(f"Frozen real snapshot: {len(papers)} candidates and {len(corpus)} library papers. No library content is included in reports.")


class ComparisonReranker(LocalReranker):
    def __init__(self, config, revision):
        super().__init__(config)
        self.revision = revision
        self.encoder = None

    def _load_encoder(self):
        from sentence_transformers import SentenceTransformer

        if self.encoder is None:
            self.encoder = SentenceTransformer(self.config.reranker.local.model, revision=self.revision, trust_remote_code=True)
        self.encoder.max_seq_length = self.config.reranker.local.max_seq_length
        return self.encoder


class FrozenVectorsReranker(BaseReranker):
    def __init__(self, config, similarity):
        super().__init__(config)
        self.similarity = similarity

    def get_similarity_score(self, s1, s2):
        return self.similarity


def rank(directory, profile):
    started = perf_counter()
    data = load(directory / "snapshot.json")
    config = OmegaConf.load(ROOT / "config" / "base.yaml")
    family = "gist" if profile == "gist512" else "jina"
    settings = config.reranker.local
    settings.model = MODELS[family]
    settings.max_seq_length = 8192 if profile == "jina8192" else 512
    settings.encode_kwargs = {} if family == "gist" else {"task": "retrieval", "prompt_name": "document"}
    settings.cache_dir = str(directory / (profile + "-cache"))
    papers = [Paper(**paper) for paper in data["candidates"]]
    corpus = [CorpusPaper(title="", abstract=paper["abstract"], paths=[], added_date=datetime.fromisoformat(paper["added_date"]))
              for paper in data["corpus"]]
    texts = [paper.abstract for paper in papers] + [paper.abstract for paper in corpus]
    ranker = ComparisonReranker(config, data["model_revisions"][family])
    reused = 0
    reuse_verified = None
    lengths = None
    if profile == "jina8192":
        # Short inputs are identical at both limits. Reuse only those well below 512, reserving
        # a conservative 32-token margin for model-specific special tokens. Re-encode all others.
        previous = np.load(directory / "jina512-vectors.npy", allow_pickle=False)
        lengths = np.load(directory / "jina-token-lengths.npy", allow_pickle=False)
        vectors = {text: previous[index] for index, text in enumerate(texts) if lengths[index] <= 480}
        missing = list(dict.fromkeys(text for text in texts if text not in vectors))
        reused = len(vectors)
        controls = list(vectors)[:3]
        encoded = ranker._encode_texts(list(dict.fromkeys(missing + controls)))
        reuse_verified = all(np.allclose(vectors[text], encoded[text], rtol=1e-4, atol=1e-5) for text in controls)
        if not reuse_verified:
            # Fall back to a full re-encode if changing the sequence limit changes short-input output.
            vectors = ranker._encode_texts(texts)
            reused = 0
        else:
            vectors.update(encoded)
    else:
        vectors = ranker._encode_texts(texts)
    matrix = np.stack([vectors[text] for text in texts])
    matrix = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    similarity = matrix[:len(papers)] @ matrix[len(papers):].T
    selected = FrozenVectorsReranker(config, similarity).rerank(papers, corpus)
    if profile == "jina512":
        prefix = ranker.encoder.prompts.get("document", "")
        lengths = np.array([len(ranker.encoder.tokenizer.encode(prefix + text, add_special_tokens=True, truncation=False)) for text in texts])
        np.save(directory / "jina512-vectors.npy", np.stack([vectors[text] for text in texts]), allow_pickle=False)
        np.save(directory / "jina-token-lengths.npy", lengths, allow_pickle=False)
    result = {"profile": profile, "model": settings.model, "revision": ranker.revision,
              "max_seq_length": settings.max_seq_length, "elapsed_seconds": round(perf_counter() - started, 2),
              "short_inputs_reused_from_jina512": reused,
              "short_input_reuse_verified": reuse_verified,
              "timing_note": "Incremental long-input sensitivity check; short vectors reused after validation" if reused else "Full encoding including model load",
              "inputs_over_512_jina_tokens": int((lengths > 512).sum()) if lengths is not None else None,
              "library_inputs_over_512_jina_tokens": int((lengths[len(papers):] > 512).sum()) if lengths is not None else None,
              "ranking": [{"id": paper.source + ":" + paper.url, "title": paper.title, "url": paper.url,
                           "score": float(paper.score)} for paper in selected]}
    save(directory / (profile + ".json"), result)
    print(f"{profile} completed in {result['elapsed_seconds']}s; no library text was printed.")


def report(directory):
    data = load(directory / "snapshot.json")
    results = {profile: load(directory / (profile + ".json")) for profile in PROFILES}
    pairs = [("gist512", "jina512"), ("gist512", "jina8192"), ("jina512", "jina8192")]
    comparisons = {left + "_vs_" + right: {str(k): ranking_agreement(results[left]["ranking"], results[right]["ranking"], k)
                                         for k in (5, 10, 20)} for left, right in pairs}
    public = {"snapshot_utc": data["captured_at"], "snapshot_sha256": hashlib.sha256((directory / "snapshot.json").read_bytes()).hexdigest(),
              "candidates": len(data["candidates"]), "library_papers": len(data["corpus"]),
              "library_abstracts_containing_cjk": data.get("library_abstracts_containing_cjk"),
              "profiles": {key: {field: value for field, value in result.items() if field != "ranking"} for key, result in results.items()},
              "agreement": comparisons,
              "top20": {key: result["ranking"][:20] for key, result in results.items()}}
    output = directory / "report"
    output.mkdir(exist_ok=True)
    save(output / "comparison.json", public)
    lookup = {paper["id"]: paper for result in results.values() for paper in result["ranking"]}
    ids = list(dict.fromkeys(paper["id"] for profile in PROFILES for paper in public["top20"][profile]))
    ranks = {key: {paper["id"]: index + 1 for index, paper in enumerate(result["ranking"])} for key, result in results.items()}
    lines = ["# Real paper selection comparison", "",
             f"Snapshot UTC: {data['captured_at']}; candidates: {len(data['candidates'])}; library papers: {len(data['corpus'])}.",
             "", "All profiles use the same texts and the production Zotero recency weighting. Scores are not calibrated across models.",
             "Agreement is not accuracy: there are no human relevance labels yet.", "",
             "| Comparison | Top-20 overlap | All-candidate Spearman |", "|---|---:|---:|"]
    for pair, metrics in comparisons.items():
        value = metrics["20"]
        correlation = value["spearman_all_candidates"]
        lines.append(f"| {pair} | {value['overlap_count']}/{value['k']} | {correlation:.3f} |" if correlation is not None
                     else f"| {pair} | {value['overlap_count']}/{value['k']} | N/A |")
    lines += ["", "## Papers selected by at least one profile", "", "| Paper | GIST 512 rank | Jina 512 rank | Jina 8192 rank |", "|---|---:|---:|---:|"]
    for key in ids:
        paper = lookup[key]
        title = paper["title"].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| [{title}]({paper['url']}) | {ranks['gist512'][key]} | {ranks['jina512'][key]} | {ranks['jina8192'][key]} |")
    text = '\n'.join(lines) + '\n'
    (output / "comparison.md").write_text(text, encoding="utf-8")
    random.Random(42).shuffle(ids)
    with (output / "blind-review.csv").open('w', encoding="utf-8-sig", newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(["paper_id", "title", "url", "relevance_0_1_2", "reason"])
        for key in ids:
            writer.writerow([key, lookup[key]["title"], lookup[key]["url"], "", ""])
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(summary).write_text(text, encoding="utf-8")
    # Notices expose only counts and public arXiv candidate titles/links, never library contents.
    print("::notice title=Real ranking comparison::" + json.dumps(public, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("snapshot", *PROFILES, "report"))
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.stage == "snapshot":
        snapshot(args.directory)
    elif args.stage == "report":
        report(args.directory)
    else:
        rank(args.directory, args.stage)
