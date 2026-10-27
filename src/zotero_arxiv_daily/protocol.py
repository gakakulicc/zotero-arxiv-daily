from dataclasses import dataclass
from typing import Optional, TypeVar
from datetime import datetime
import re
import tiktoken
from openai import OpenAI
from .local_llm import LocalLLM
from loguru import logger
import json
RawPaperItem = TypeVar('RawPaperItem')


def _request_llm(openai_client: OpenAI | LocalLLM, llm_params: dict, messages: list[dict], json_output: bool = False) -> str:
    if llm_params.get("backend", "api") == "local":
        if json_output:
            return openai_client.generate(messages, json_output=True)
        return openai_client.generate(messages)
    api_mode = llm_params.get("api_mode", "chat_completion")
    generation_kwargs = dict(llm_params.get("generation_kwargs", {}))

    if api_mode == "chat_completion":
        response = openai_client.chat.completions.create(
            messages=messages,
            **generation_kwargs,
        )
        return response.choices[0].message.content

    if api_mode == "response":
        max_tokens = generation_kwargs.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in generation_kwargs:
            generation_kwargs["max_output_tokens"] = max_tokens
        response = openai_client.responses.create(
            input=messages,
            **generation_kwargs,
        )
        return response.output_text

    raise ValueError(
        f"Unsupported llm.api_mode: {api_mode}. "
        "Expected 'chat_completion' or 'response'."
    )


def _truncate_prompt(client: OpenAI | LocalLLM, llm_params: dict, prompt: str, limit: int) -> str:
    if llm_params.get("backend", "api") == "local":
        return client.truncate_prompt(prompt, limit)
    enc = tiktoken.encoding_for_model("gpt-4o")
    return enc.decode(enc.encode(prompt)[:limit])


@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    full_text: Optional[str] = None
    tldr: Optional[str] = None
    affiliations: Optional[list[str]] = None
    score: Optional[float] = None

    def _generate_insights_with_llm(self, client: OpenAI | LocalLLM, llm_params: dict) -> tuple[str, list[str]]:
        lang = llm_params.get("language", "English")
        prompt = f"Title: {self.title}\nAbstract: {self.abstract}\n"
        if self.full_text:
            prompt += f"Paper text (beginning):\n{self.full_text}"
        limit = llm_params.get("local", {}).get("input_tokens", 2000)
        prompt = _truncate_prompt(client, llm_params, prompt, limit)
        output = _request_llm(client, llm_params, [
            {"role": "system", "content": (
                f"Summarize the scientific paper in one sentence in {lang} and extract the authors' institutions. "
                'Return exactly one JSON object: {"tldr": "summary", "affiliations": ["institution"]}. '
                "Use an empty affiliations list if the text gives no institutions. Do not guess institutions. "
                "Return valid JSON only, without markdown or explanations."
            )},
            {"role": "user", "content": prompt},
        ], json_output=True)
        # Accept surrounding code fences, but validate the actual JSON and field types.
        start, end = output.find('{'), output.rfind('}')
        if start < 0 or end < start:
            raise ValueError("Local model did not return a JSON object")
        data = json.loads(output[start:end + 1])
        summary, affiliations = data.get("tldr"), data.get("affiliations")
        if (not isinstance(summary, str) or not summary.strip()
                or not isinstance(affiliations, list) or any(not isinstance(item, str) for item in affiliations)):
            raise ValueError("Local model returned invalid summary or affiliations fields")
        return summary, list(dict.fromkeys(affiliations))

    def generate_insights(self, client: OpenAI | LocalLLM, llm_params: dict) -> str:
        try:
            self.tldr, self.affiliations = self._generate_insights_with_llm(client, llm_params)
        except Exception as exc:
            logger.warning(f"Failed to generate combined summary of {self.url}; using abstract: {exc}")
            self.tldr, self.affiliations = self.abstract, None
        return self.tldr

    def _generate_tldr_with_llm(self, openai_client:OpenAI | LocalLLM,llm_params:dict) -> str:
        lang = llm_params.get('language', 'English')
        prompt = f"Given the following information of a paper, generate a one-sentence TLDR summary in {lang}:\n\n"
        if self.title:
            prompt += f"Title:\n {self.title}\n\n"

        if self.abstract:
            prompt += f"Abstract: {self.abstract}\n\n"

        if self.full_text:
            prompt += f"Preview of main content:\n {self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"
        
        prompt = _truncate_prompt(openai_client, llm_params, prompt, 4000)
        
        tldr = _request_llm(
            openai_client,
            llm_params,
            [
                {
                    "role": "system",
                    "content": f"You are an assistant who perfectly summarizes scientific paper, and gives the core idea of the paper to the user. Your answer should be in {lang}.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        return tldr
    
    def generate_tldr(self, openai_client:OpenAI | LocalLLM,llm_params:dict) -> str:
        try:
            tldr = self._generate_tldr_with_llm(openai_client,llm_params)
            self.tldr = tldr
            return tldr
        except Exception as e:
            logger.warning(f"Failed to generate tldr of {self.url}: {e}")
            tldr = self.abstract
            self.tldr = tldr
            return tldr

    def _generate_affiliations_with_llm(self, openai_client:OpenAI | LocalLLM,llm_params:dict) -> Optional[list[str]]:
        if self.full_text is not None:
            prompt = f"Given the beginning of a paper, extract the affiliations of the authors in a python list format, which is sorted by the author order. If there is no affiliation found, return an empty list '[]':\n\n{self.full_text}"
            prompt = _truncate_prompt(openai_client, llm_params, prompt, 2000)
            affiliations = _request_llm(
                openai_client,
                llm_params,
                [
                    {
                        "role": "system",
                        "content": "You are an assistant who perfectly extracts affiliations of authors from a paper. You should return a python list of affiliations sorted by the author order, like [\"TsingHua University\",\"Peking University\"]. If an affiliation is consisted of multi-level affiliations, like 'Department of Computer Science, TsingHua University', you should return the top-level affiliation 'TsingHua University' only. Do not contain duplicated affiliations. If there is no affiliation found, you should return an empty list [ ]. You should only return the final list of affiliations, and do not return any intermediate results.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )

            affiliations = re.search(r'\[.*?\]', affiliations, flags=re.DOTALL).group(0)
            affiliations = json.loads(affiliations)
            affiliations = list(set(affiliations))
            affiliations = [str(a) for a in affiliations]

            return affiliations
    
    def generate_affiliations(self, openai_client:OpenAI | LocalLLM,llm_params:dict) -> Optional[list[str]]:
        try:
            affiliations = self._generate_affiliations_with_llm(openai_client,llm_params)
            self.affiliations = affiliations
            return affiliations
        except Exception as e:
            logger.warning(f"Failed to generate affiliations of {self.url}: {e}")
            self.affiliations = None
            return None
@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]
