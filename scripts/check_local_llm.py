"""Exercise real GGUF inference in CI without Zotero, SMTP, or LLM API credentials."""

from pathlib import Path
import json
import argparse

from loguru import logger
from omegaconf import OmegaConf

from zotero_arxiv_daily.local_llm import LocalLLM
from zotero_arxiv_daily.protocol import Paper


def main(profile="default"):
    config = OmegaConf.load(Path(__file__).resolve().parents[1] / "config" / "base.yaml")
    if profile != "default":
        config.llm.local = OmegaConf.merge(config.llm.local, OmegaConf.load(
            Path(__file__).resolve().parents[1] / "config" / "models" / (profile + ".yaml")))
    config.llm.backend = "local"
    assert config.llm.local.n_ctx == 8192
    client = LocalLLM(config.llm.local)
    paper = Paper(
        source="smoke-test",
        title="Local inference for scientific paper summaries",
        authors=["Test Author"],
        abstract="We summarize scientific papers with a quantized language model running entirely on a CPU. No remote LLM API is used.",
        url="https://example.com/smoke-test",
    )
    robotics = Paper(
        source="smoke-test", title="Action-conditioned visual policies for tabletop manipulation",
        authors=["Test Author"], url="https://example.com/robotics-test",
        abstract="We study a vision-language-action policy for tabletop object placement.",
        full_text=("\\author{Test Author, Stanford University}\n\\maketitle\n\\section{Introduction}\n" + "Prior work studies robot learning. " * 600
                   + "\n\\section{Method}\nWe train a visual policy conditioned on language commands and predict discrete robot actions."
                   + "\n\\section{Experiments}\nOn two simulated robot arms, the policy succeeds on 60 of 100 trials. A baseline succeeds on 45 of 100 trials."
                   + "\n\\section{Limitations}\nReal robots and unseen environments were not tested."
                   + "\n\\section{Conclusion}\nThe study supports improved performance on this simulated benchmark only."),
    )
    unstructured = Paper(
        source="smoke-test", title="Finite context for paper summaries", authors=["Test Author"],
        abstract="We investigate whether selecting sections changes the evidence available to a summarizer.",
        full_text="Authors: Test Author. Affiliation: Stanford University.\nAbstract\n" + "We select evidence from the paper text. " * 300
                  + "The supplied text reports no measured accuracy or comparison with a baseline.",
        url="https://example.com/unstructured-test",
    )
    outputs = []
    for index, item in enumerate((paper, robotics, unstructured)):
        config.llm.language = "Chinese" if index == 1 else "English"
        # Use the strict method: fallback output must never make this integration check pass.
        summary = item._generate_tldr_with_llm(client, config.llm)
        affiliations = item._generate_affiliations_with_llm(client, config.llm)
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("The local GGUF model did not generate a summary")
        if item.full_text and (not affiliations or "Stanford University" not in affiliations):
            raise RuntimeError(f"Independent institution extraction missed an explicit institution: {affiliations}")
        if '<think>' in summary or '</think>' in summary:
            raise RuntimeError("The final summary contains reasoning delimiters")
        if index == 0:
            unsupported = ("competitive summary quality", "reducing latency", "consumer hardware", "experimental results demonstrate")
            if any(phrase in summary.lower() for phrase in unsupported):
                raise RuntimeError("The abstract-only control invented evaluation or hardware claims")
        outputs.append({"profile": profile, "model": config.llm.local.repo_id, "filename": config.llm.local.filename,
                        "title": item.title, "summary": summary, "affiliations": affiliations, "evidence_scope": item.evidence_scope})
        logger.info(f"Real local Qwen batch item {index + 1}/3 succeeded: {summary}")
    print("::notice title=Real local summary batch::" + json.dumps(outputs, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("default", "qwen25", "qwen35"), default="default")
    args = parser.parse_args()
    try:
        main(args.profile)
    except Exception as exc:
        print("::error title=Local model validation::" + (type(exc).__name__ + ': ' + str(exc)).replace('\n', ' '))
        raise
