"""Local inference routing and context limits, without downloading a model."""

import sys

import pytest

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.local_llm import LocalLLM


def test_local_summary_and_affiliations_reuse_one_model(config, stub_local_llm, monkeypatch):
    config.llm.backend = "local"
    client = LocalLLM(config.llm.local)
    paper = make_sample_paper()
    monkeypatch.setattr(
        "zotero_arxiv_daily.protocol.tiktoken.encoding_for_model",
        lambda *args: pytest.fail("Local inference must use the GGUF tokenizer"),
    )

    assert paper.generate_tldr(client, config.llm) == "Local summary"
    assert set(paper.generate_affiliations(client, config.llm)) == {"TsingHua University", "Peking University"}
    assert len(stub_local_llm.loads) == 1
    assert stub_local_llm.loads[0]["n_ctx"] == 8192
    assert stub_local_llm.loads[0]["n_threads"] == 4
    assert all(request["max_tokens"] == 512 for request in stub_local_llm.requests)
    assert all(request["temperature"] == 0 for request in stub_local_llm.requests)
    # API generation kwargs (including max_tokens=16384 and model) must not leak into llama.cpp.
    assert all("model" not in request for request in stub_local_llm.requests)


def test_existing_gguf_does_not_download(config, stub_local_llm):
    config.llm.local.model_path = "models/existing.gguf"
    client = LocalLLM(config.llm.local)
    assert stub_local_llm.loads == []  # Lazy loading.
    assert client.generate([{"role": "user", "content": "Summarize"}]) == "Local summary"
    assert stub_local_llm.downloads == []
    assert stub_local_llm.loads[0]["model_path"] == "models/existing.gguf"


def test_local_context_reserves_output_and_preserves_system(config, stub_local_llm):
    client = LocalLLM(config.llm.local)
    messages = [
        {"role": "system", "content": "Keep this instruction"},
        {"role": "user", "content": "word " * 10000},
    ]
    client.generate(messages)
    request = stub_local_llm.requests[0]
    assert request["messages"][0] == messages[0]
    size = sum(len(message["content"].encode()) for message in request["messages"])
    assert size + request["max_tokens"] + 64 + 16 * len(messages) <= config.llm.local.n_ctx
    assert len(messages[-1]["content"]) == 50000  # Caller messages were not mutated.


@pytest.mark.parametrize("max_tokens", [0, -1, 8192, 9000])
def test_local_rejects_invalid_token_budget(config, stub_local_llm, max_tokens):
    config.llm.local.max_tokens = max_tokens
    with pytest.raises(ValueError, match="max_tokens"):
        LocalLLM(config.llm.local)


def test_local_missing_dependency_has_install_instructions(config, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    with pytest.raises(RuntimeError, match="uv sync --extra local-llm"):
        LocalLLM(config.llm.local)


def test_local_rejects_oversized_system_prompt(config, stub_local_llm):
    client = LocalLLM(config.llm.local)
    with pytest.raises(ValueError, match="context is too small"):
        client.generate([
            {"role": "system", "content": "instruction " * 1000},
            {"role": "user", "content": "Summarize"},
        ])
    assert stub_local_llm.requests == []


def test_combined_insights_make_one_local_request(config, stub_local_llm):
    config.llm.backend = "local"
    paper = make_sample_paper()
    assert paper.generate_insights(LocalLLM(config.llm.local), config.llm) == "Local summary"
    assert len(stub_local_llm.requests) == 1
    assert set(paper.affiliations) == {"TsingHua University", "Peking University"}
    assert stub_local_llm.requests[0]["max_tokens"] == 512
    assert stub_local_llm.requests[0]["response_format"]["type"] == "json_object"


@pytest.mark.parametrize("output", ["not json", '{"tldr": "ok", "affiliations": "bad"}', '{"tldr": "", "affiliations": []}'])
def test_combined_insights_fall_back_without_retrying_expensive_generation(config, output):
    from types import SimpleNamespace

    config.llm.backend = "local"
    calls = []
    client = SimpleNamespace(truncate_prompt=lambda text, limit: text,
                             generate=lambda messages, **kwargs: calls.append(messages) or output)
    paper = make_sample_paper()
    assert paper.generate_insights(client, config.llm) == paper.abstract
    assert paper.affiliations is None
    assert len(calls) == 1
