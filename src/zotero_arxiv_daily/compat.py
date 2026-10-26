"""Keep the pre-1.0 Actions settings working with the YAML-based pipeline."""

import os
import re
from collections.abc import Mapping

from omegaconf import DictConfig, OmegaConf


def apply_legacy_environment(config: DictConfig, environ: Mapping[str, str] | None = None) -> None:
    environ = os.environ if environ is None else environ
    values = {key: value.strip() for key, value in environ.items() if value.strip()}

    def boolean(key):
        value = values[key].lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError(f"{key} must be true, false, 1, or 0")
        return value in {"true", "1"}

    for key, path in {
        "SMTP_SERVER": "email.smtp_server",
        "LANGUAGE": "llm.language",
        "MODEL_NAME": "llm.generation_kwargs.model",
        "ZOTERO_IGNORE": "zotero.legacy_ignore_patterns",
    }.items():
        if key in values:
            OmegaConf.update(config, path, values[key])
    for key, path in {"SEND_EMPTY": "executor.send_empty", "DEBUG": "executor.debug"}.items():
        if key in values:
            OmegaConf.update(config, path, boolean(key))
    if "SMTP_PORT" in values:
        port = int(values["SMTP_PORT"])
        if not 1 <= port <= 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535")
        config.email.smtp_port = port
    if "MAX_PAPER_NUM" in values:
        limit = int(values["MAX_PAPER_NUM"])
        if limit != -1 and limit < 1:
            raise ValueError("MAX_PAPER_NUM must be positive, or -1 for all papers")
        config.executor.max_paper_num = limit
    if "ARXIV_QUERY" in values:
        categories = [part.strip() for part in values["ARXIV_QUERY"].split('+')]
        if not all(re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)?', part) for part in categories):
            raise ValueError("ARXIV_QUERY must be RSS categories such as cs.AI+cs.CV; alternatively remove it and set source.arxiv.category in CUSTOM_CONFIG")
        config.source.arxiv.category = list(dict.fromkeys(categories))
    if "LLM_BACKEND" in values:
        config.llm.backend = values["LLM_BACKEND"]
    elif "USE_LLM_API" in values:
        config.llm.backend = "api" if boolean("USE_LLM_API") else "local"
