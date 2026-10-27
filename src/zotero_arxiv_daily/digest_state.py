"""Recover completed public-paper summaries and record acknowledged SMTP deliveries."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from loguru import logger
from omegaconf import OmegaConf


class DigestState:
    def __init__(self, directory):
        self.connection = None
        if not directory:
            return
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(Path(directory) / "state.sqlite3")
            self.connection.execute("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, payload TEXT, saved TEXT)")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            self.connection.execute("DELETE FROM records WHERE saved < ?", (cutoff,))
            self.connection.commit()
        except (OSError, sqlite3.Error):
            logger.warning("Digest checkpoint unavailable; continuing without it")
            self.close()

    def get(self, key):
        if self.connection:
            try:
                row = self.connection.execute("SELECT payload FROM records WHERE key=?", (key,)).fetchone()
                return json.loads(row[0]) if row else None
            except (sqlite3.Error, ValueError):
                logger.warning("Could not read digest checkpoint; recomputing")
        return None

    def put(self, key, payload):
        if self.connection:
            try:
                self.connection.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
                                        (key, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
                self.connection.commit()
            except (sqlite3.Error, TypeError):
                logger.warning("Could not save digest checkpoint")

    @staticmethod
    def paper_key(paper, config):
        # Never serialize the whole configuration: it contains SMTP, Zotero and API credentials.
        local = config.llm.get("local", {})
        generation = config.llm.get("generation_kwargs") or {}
        if OmegaConf.is_config(generation):
            generation = OmegaConf.to_container(generation)
        identity = {"version": 2, "url": paper.url, "title": paper.title, "abstract": paper.abstract,
                    "language": config.llm.get("language"), "backend": config.llm.get("backend"),
                    "combined": config.executor.get("combine_llm_requests", True),
                    "full_text": config.executor.get("fetch_full_text", True),
                    "generation_kwargs": generation,
                    "local": {key: local.get(key) for key in ("repo_id", "filename", "model_path", "n_ctx", "max_tokens", "input_tokens", "temperature")}}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return "paper:" + digest

    def restore_paper(self, key, paper):
        data = self.get(key)
        if (not isinstance(data, dict) or not isinstance(data.get("tldr"), str) or not data["tldr"].strip()
                or data.get("generation_status") != "generated"):
            return False
        affiliations = data.get("affiliations")
        if affiliations is not None and (not isinstance(affiliations, list) or any(not isinstance(x, str) for x in affiliations)):
            return False
        for field in ("tldr", "affiliations", "generation_status", "evidence_scope"):
            setattr(paper, field, data.get(field))
        return True

    def save_paper(self, key, paper):
        if paper.generation_status == "generated":
            self.put(key, {name: getattr(paper, name) for name in ("tldr", "affiliations", "generation_status", "evidence_scope")})

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
