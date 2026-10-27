"""Root conftest: config fixtures and shared helpers.

All mocking uses pytest monkeypatch + SimpleNamespace. No unittest.mock.
"""

import copy

import pytest
from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from pathlib import Path

_CONFIG_DIR = str(Path(__file__).resolve().parent.parent / "config")


@pytest.fixture(scope="session")
def _base_config():
    """Session-scoped Hydra config with all required values filled in.

    Never mutate this directly; use the function-scoped ``config`` fixture.
    """
    GlobalHydra.instance().clear()
    with initialize_config_dir(config_dir=_CONFIG_DIR, version_base=None):
        cfg = compose(
            config_name="default",
            overrides=[
                "zotero.user_id=000000",
                "zotero.api_key=fake-zotero-key",
                "zotero.include_path=null",
                "zotero.ignore_path=null",
                "email.sender=test@example.com",
                "email.receiver=test@example.com",
                "email.smtp_server=localhost",
                "email.smtp_port=1025",
                "email.sender_password=test",
                "llm.api.key=sk-fake",
                "llm.backend=api",
                "llm.api.base_url=http://localhost:30000/v1",
                "llm.generation_kwargs.model=gpt-4o-mini",
                "reranker.api.key=sk-fake",
                "reranker.api.base_url=http://localhost:30000/v1",
                "reranker.api.model=text-embedding-3-large",
                "reranker.local.cache_dir=null",
                "source.arxiv.category=[cs.AI,cs.CV]",
                "executor.source=[arxiv]",
                "executor.reranker=api",
                "executor.debug=false",
                "executor.send_empty=false",
                "executor.state_dir=null",
                "executor.report_dir=null",
                "llm.summary_attempts=1",
            ],
        )
    return cfg


@pytest.fixture()
def config(_base_config):
    """Function-scoped deep copy of the session config.

    Safe to mutate inside any test without polluting other tests.
    """
    return copy.deepcopy(_base_config)


@pytest.fixture()
def stub_local_llm(monkeypatch):
    import sys
    from types import SimpleNamespace

    state = SimpleNamespace(loads=[], downloads=[], requests=[])

    class FakeLlama:
        def __init__(self, **kwargs):
            state.loads.append(kwargs)

        @classmethod
        def from_pretrained(cls, **kwargs):
            state.downloads.append(kwargs)
            return cls(**kwargs)

        def tokenize(self, text, **kwargs):
            return list(text)

        def detokenize(self, tokens):
            return bytes(tokens)

        def create_chat_completion(self, **kwargs):
            state.requests.append(kwargs)
            content = ('{"tldr": "Local summary", "affiliations": ["TsingHua University", "Peking University"]}'
                       if "JSON object" in kwargs["messages"][0]["content"] else
                       '["TsingHua University", "Peking University"]'
                       if "affiliations" in kwargs["messages"][0]["content"]
                       else "Local summary")
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(Llama=FakeLlama))
    return state
