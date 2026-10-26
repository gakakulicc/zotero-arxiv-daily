"""Old repository Secrets and Variables remain usable after the upstream migration."""

import pytest
from omegaconf import OmegaConf

from zotero_arxiv_daily.compat import apply_legacy_environment


def test_old_action_settings(config):
    apply_legacy_environment(config, {
        "SMTP_SERVER": " smtp.example.com ", "SMTP_PORT": "587",
        "LANGUAGE": "Chinese", "MODEL_NAME": "my-api-model", "USE_LLM_API": "false",
        "SEND_EMPTY": "false", "MAX_PAPER_NUM": "-1", "ARXIV_QUERY": "cs.CV+cs.LG",
        "ZOTERO_IGNORE": "archive/**\n!archive/keep/**", "DEBUG": "0",
    })
    assert config.email.smtp_server == "smtp.example.com"
    assert config.email.smtp_port == 587
    assert config.llm.language == "Chinese"
    assert config.llm.backend == "local"
    assert config.llm.generation_kwargs.model == "my-api-model"
    assert config.executor.send_empty is False
    assert config.executor.debug is False
    assert config.executor.max_paper_num == -1
    assert list(config.source.arxiv.category) == ["cs.CV", "cs.LG"]
    assert config.zotero.legacy_ignore_patterns == "archive/**\n!archive/keep/**"


def test_empty_legacy_settings_do_not_override_yaml(config):
    before = OmegaConf.to_container(config)
    apply_legacy_environment(config, {key: "" for key in (
        "SMTP_SERVER", "SMTP_PORT", "USE_LLM_API", "SEND_EMPTY", "MAX_PAPER_NUM", "ARXIV_QUERY",
    )})
    assert OmegaConf.to_container(config) == before


def test_explicit_backend_overrides_legacy_flag(config):
    apply_legacy_environment(config, {"USE_LLM_API": "true", "LLM_BACKEND": "local"})
    assert config.llm.backend == "local"


@pytest.mark.parametrize("settings", [
    {"SMTP_PORT": "0"}, {"MAX_PAPER_NUM": "-2"}, {"SEND_EMPTY": "maybe"},
    {"ARXIV_QUERY": "cs.AI+invalid query"},
])
def test_invalid_old_setting_fails_early(config, settings):
    with pytest.raises(ValueError):
        apply_legacy_environment(config, settings)


def test_legacy_gitignore_keeps_negation_rules():
    from datetime import datetime
    from zotero_arxiv_daily.executor import Executor
    from zotero_arxiv_daily.protocol import CorpusPaper

    executor = Executor.__new__(Executor)
    executor.config = OmegaConf.create({"zotero": {"legacy_ignore_patterns": "archive/**\n!archive/keep/**"}})
    executor.include_path_patterns = None
    executor.ignore_path_patterns = None
    corpus = [CorpusPaper(title=path, abstract="", added_date=datetime(2026, 1, 1), paths=[path])
              for path in ["archive/drop/paper", "archive/keep/paper", "active/paper"]]
    assert [paper.title for paper in executor.filter_corpus(corpus)] == ["archive/keep/paper", "active/paper"]


def test_invalid_receivers_fail_before_model_or_network(config, monkeypatch):
    from zotero_arxiv_daily.executor import Executor

    config.email.receiver = "not-an-address"
    monkeypatch.setattr("zotero_arxiv_daily.executor.get_retriever_cls", lambda *args: pytest.fail("No retriever should be created"))
    with pytest.raises(ValueError, match="RECEIVER"):
        Executor(config)
