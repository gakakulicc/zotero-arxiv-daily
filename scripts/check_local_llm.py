"""Exercise real GGUF inference in CI without Zotero, SMTP, or LLM API credentials."""

from pathlib import Path

from loguru import logger
from omegaconf import OmegaConf

from zotero_arxiv_daily.local_llm import LocalLLM
from zotero_arxiv_daily.protocol import Paper


def main():
    config = OmegaConf.load(Path(__file__).resolve().parents[1] / "config" / "base.yaml")
    config.llm.backend = "local"
    assert config.llm.local.n_ctx == 8192
    assert config.llm.local.max_tokens == 512
    client = LocalLLM(config.llm.local)
    paper = Paper(
        source="smoke-test",
        title="Local inference for scientific paper summaries",
        authors=["Test Author"],
        abstract="We summarize scientific papers with a quantized language model running entirely on a CPU. No remote LLM API is used.",
        url="https://example.com/smoke-test",
    )
    # Call the strict method: the public method intentionally falls back to the abstract on failure.
    summary = paper._generate_tldr_with_llm(client, config.llm)
    if not isinstance(summary, str) or not summary.strip():
        raise RuntimeError("The local GGUF model did not generate a summary")
    logger.info(f"Real local Qwen inference succeeded: {summary}")


if __name__ == "__main__":
    main()
