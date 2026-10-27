from .base import BaseReranker, register_reranker
import logging
import warnings
import numpy as np
from loguru import logger
from time import sleep
import hashlib
import json
import sqlite3
from pathlib import Path
from omegaconf import OmegaConf
@register_reranker("local")
class LocalReranker(BaseReranker):
    def _load_encoder(self):
        from sentence_transformers import SentenceTransformer
        if not self.config.executor.debug:
            from transformers.utils import logging as transformers_logging
            from huggingface_hub.utils import logging as hf_logging
    
            transformers_logging.set_verbosity_error()
            hf_logging.set_verbosity_error()
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            logging.getLogger("sentence_transformers.SentenceTransformer").setLevel(logging.ERROR)
            logging.getLogger("transformers").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
            warnings.filterwarnings("ignore", category=FutureWarning)

        for attempt in range(3):
            try:
                encoder = SentenceTransformer(self.config.reranker.local.model, trust_remote_code=True)
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"Failed to load model after 3 attempts: {e}") from e
                wait = 30 * (attempt + 1)
                logger.warning(f"Failed to load model (attempt {attempt+1}/3), retrying in {wait}s...")
                sleep(wait)
        encoder.max_seq_length = self.config.reranker.local.get("max_seq_length", 512)
        return encoder

    def _encode_texts(self, texts: list[str]) -> dict[str, np.ndarray]:
        settings = self.config.reranker.local
        namespace = json.dumps({
            "version": 1, "model": settings.model,
            "max_seq_length": settings.get("max_seq_length", 512),
            "encode_kwargs": OmegaConf.to_container(settings.encode_kwargs) if settings.encode_kwargs else {},
        }, sort_keys=True)
        unique_texts = list(dict.fromkeys(texts))
        keys = {text: hashlib.sha256((namespace + '\0' + text).encode()).hexdigest() for text in unique_texts}
        vectors = {}
        connection = None
        directory = settings.get("cache_dir")
        if directory:
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(Path(directory) / "vectors.sqlite3")
                connection.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, dimension INTEGER, vector BLOB)")
                for text, key in keys.items():
                    row = connection.execute("SELECT dimension, vector FROM vectors WHERE key = ?", (key,)).fetchone()
                    if row:
                        vector = np.frombuffer(row[1], dtype='<f4')
                        if len(vector) == row[0] and len(vector) > 0 and np.isfinite(vector).all():
                            vectors[text] = vector
            except (OSError, sqlite3.Error, ValueError) as exc:
                logger.warning(f"Embedding cache unavailable; computing embeddings: {exc}")
                if connection:
                    connection.close()
                connection = None
                vectors = {}

        missing = [text for text in unique_texts if text not in vectors]
        logger.info(f"Embedding cache: {len(vectors)} hits, {len(missing)} new texts")
        try:
            if missing:
                encoder = self._load_encoder()
                kwargs = dict(settings.encode_kwargs or {})
                kwargs.setdefault("batch_size", settings.get("batch_size", 32))
                kwargs.setdefault("show_progress_bar", True)
                kwargs["convert_to_numpy"] = True
                encoded = np.asarray(encoder.encode(missing, **kwargs), dtype='<f4')
                if (encoded.ndim != 2 or encoded.shape[0] != len(missing)
                        or encoded.shape[1] == 0 or not np.isfinite(encoded).all()):
                    raise ValueError("Embedding model returned invalid vectors")
                vectors.update(zip(missing, encoded))
                if connection:
                    try:
                        connection.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)",
                                               [(keys[text], len(vector), vector.tobytes()) for text, vector in zip(missing, encoded)])
                        connection.commit()
                    except sqlite3.Error as exc:
                        logger.warning(f"Could not update embedding cache: {exc}")
            return vectors
        finally:
            if connection:
                connection.close()

    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        if not s1 or not s2:
            return np.empty((len(s1), len(s2)))
        vectors = self._encode_texts(s1 + s2)
        left = np.stack([vectors[text] for text in s1])
        right = np.stack([vectors[text] for text in s2])
        left = left / np.maximum(np.linalg.norm(left, axis=1, keepdims=True), 1e-12)
        right = right / np.maximum(np.linalg.norm(right, axis=1, keepdims=True), 1e-12)
        return left @ right.T
