"""Direct GGUF inference without an API server or API credentials."""

from functools import cached_property

from loguru import logger
from omegaconf import DictConfig


class LocalLLM:
    def __init__(self, config: DictConfig):
        self.config = config
        if not 0 < config.max_tokens < config.n_ctx:
            raise ValueError("llm.local.max_tokens must be positive and smaller than n_ctx")
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "Local LLM requires llama-cpp-python. Run: uv sync --extra local-llm"
            ) from exc
        self._llama_cls = Llama

    @cached_property
    def model(self):
        kwargs = dict(n_ctx=self.config.n_ctx, n_threads=self.config.n_threads, verbose=False)
        if self.config.model_path:
            logger.info("Loading local GGUF model")
            return self._llama_cls(model_path=self.config.model_path, **kwargs)
        logger.info(f"Loading GGUF model from {self.config.repo_id}")
        return self._llama_cls.from_pretrained(
            repo_id=self.config.repo_id, filename=self.config.filename, **kwargs
        )

    def _tokens(self, text: str) -> list[int]:
        return self.model.tokenize(text.encode("utf-8"), add_bos=False, special=False)

    def truncate_prompt(self, prompt: str, max_tokens: int) -> str:
        tokens = self._tokens(prompt)
        return self.model.detokenize(tokens[:max_tokens]).decode("utf-8", errors="ignore")

    def generate(self, messages: list[dict], json_output: bool = False) -> str:
        messages = [dict(message) for message in messages]
        # Reserve room for the chat template and output, using the GGUF tokenizer.
        budget = self.config.n_ctx - self.config.max_tokens - 64 - 16 * len(messages)
        prefix_size = sum(len(self._tokens(message["content"])) for message in messages[:-1])
        if prefix_size >= budget:
            raise ValueError("Local LLM context is too small for the system prompt and output")
        messages[-1]["content"] = self.truncate_prompt(messages[-1]["content"], budget - prefix_size)
        kwargs = {}
        if json_output:
            kwargs["response_format"] = {"type": "json_object", "schema": {
                "type": "object",
                "properties": {"tldr": {"type": "string"},
                               "affiliations": {"type": "array", "items": {"type": "string"}}},
                "required": ["tldr", "affiliations"], "additionalProperties": False,
            }}
        response = self.model.create_chat_completion(
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            **kwargs,
        )
        return response["choices"][0]["message"]["content"]
