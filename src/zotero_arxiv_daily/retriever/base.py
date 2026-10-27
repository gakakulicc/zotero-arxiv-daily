from abc import ABC, abstractmethod
from omegaconf import DictConfig
from ..protocol import Paper, RawPaperItem
from tqdm import tqdm
from typing import Type
from time import sleep
from loguru import logger


class BaseRetriever(ABC):
    name: str
    def __init__(self, config:DictConfig):
        self.config = config
        self.retriever_config = getattr(config.source,self.name)

    @abstractmethod
    def _retrieve_raw_papers(self) -> list[RawPaperItem]:
        pass

    @abstractmethod
    def convert_to_paper(self, raw_paper:RawPaperItem) -> Paper | None:
        pass

    def enrich_paper(self, paper: Paper) -> Paper:
        """Fetch optional full text after ranking; metadata-only sources need no work."""
        return paper

    def retrieve_papers(self) -> list[Paper]:
        raw_papers = self._retrieve_raw_papers()
        logger.info("Processing papers...")
        papers = []
        conversion_errors = 0
        for raw_paper in tqdm(raw_papers, total=len(raw_papers), desc="Converting papers"):
            try:
                paper = self.convert_to_paper(raw_paper)
            except Exception as exc:
                conversion_errors += 1
                logger.warning(f"Skipping paper {getattr(raw_paper, 'title', raw_paper)}: {exc}")
                continue
            if paper is not None:
                papers.append(paper)
            delay = self.config.executor.get("conversion_delay", 0)
            if delay:
                sleep(delay)
        if raw_papers and conversion_errors == len(raw_papers):
            raise RuntimeError("The source returned entries but all failed metadata conversion")
        return papers

registered_retrievers = {}

def register_retriever(name:str):
    def decorator(cls):
        registered_retrievers[name] = cls
        cls.name = name
        return cls
    return decorator

def get_retriever_cls(name:str) -> Type[BaseRetriever]:
    if name not in registered_retrievers:
        raise ValueError(f"Retriever {name} not found")
    return registered_retrievers[name]
