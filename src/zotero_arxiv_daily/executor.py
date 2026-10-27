from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig, ListConfig
from .utils import glob_match
from .retriever import get_retriever_cls
from .protocol import CorpusPaper
import random
from datetime import datetime, timedelta, timezone
import hashlib
import os
from .reranker import get_reranker_cls
from .construct_email import render_email
from .utils import send_email, parse_receivers
from openai import OpenAI
from .local_llm import LocalLLM
from tqdm import tqdm
from time import perf_counter
from .digest_state import DigestState
from .reporting import record_delivery


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        parse_receivers(config.email.receiver)  # Fail before fetching papers or loading models.
        self.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
        self.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        backend = config.llm.get("backend", "api")
        if backend == "local":
            self.openai_client = LocalLLM(config.llm.local)
        elif backend == "api":
            self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url, timeout=120, max_retries=2)
        else:
            raise ValueError(f"Unsupported llm.backend: {backend}. Expected 'local' or 'api'.")
    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        legacy_patterns = self.config.zotero.get("legacy_ignore_patterns")
        if legacy_patterns:
            from gitignore_parser import parse_gitignore
            from pathlib import Path
            from tempfile import TemporaryDirectory
            import os

            with TemporaryDirectory() as directory:
                ignore_file = Path(directory) / "legacy.gitignore"
                ignore_file.write_text(legacy_patterns, encoding="utf-8")
                matcher = parse_gitignore(str(ignore_file), base_dir=os.getcwd())
                corpus = [paper for paper in corpus if not any(matcher(path) for path in paper.paths)]
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    
    def run(self):
        self.notices = []
        self.delivery_attempted = False
        state = DigestState(self.config.executor.get("state_dir"))
        day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        target = '\0'.join([self.config.email.sender, *parse_receivers(self.config.email.receiver),
                            "test" if self.config.executor.debug else "daily"])
        self.delivery_key = "delivered:" + day + ':' + hashlib.sha256(target.encode()).hexdigest()
        try:
            if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and state.get(self.delivery_key):
                logger.info("Today's scheduled digest was already accepted by SMTP; skipping the retry slot")
                record_delivery(self.config.executor.get("report_dir"), "", "already_delivered", [], [])
                return
            self._run(state)
        except Exception as exc:
            # A failed retrieval is never presented as a normal day with no new papers.
            if not self.delivery_attempted:
                self.notices.append(f"Daily digest could not complete ({type(exc).__name__}). 检索或排序失败，不能据此判断当天没有新论文。")
                try:
                    self._deliver([], state, failure=True)
                except Exception as notification_error:
                    logger.error(f"Failure notification could not be sent: {type(notification_error).__name__}")
            raise
        finally:
            state.close()

    def _deliver(self, papers, state, failure=False):
        html = render_email(papers, self.notices)
        directory = self.config.executor.get("report_dir")
        self.delivery_attempted = True
        record_delivery(directory, html, "prepared", papers, self.notices)
        try:
            send_email(self.config, html)
        except Exception:
            record_delivery(directory, html, "smtp_failed_or_unconfirmed", papers, self.notices)
            raise
        record_delivery(directory, html, "failure_notice_sent" if failure else "smtp_accepted", papers, self.notices)
        if not failure:
            state.put(self.delivery_key, {"smtp_accepted": True})

    def _run(self, state):
        started = perf_counter()
        corpus = self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
        if len(corpus) == 0:
            raise RuntimeError("No usable Zotero abstracts remain after filtering; check library and collection settings")
        all_papers = []
        sources_failed = 0
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            try:
                papers = retriever.retrieve_papers()
            except Exception as exc:
                sources_failed += 1
                self.notices.append(f"Source {source} could not be retrieved ({type(exc).__name__}); this digest may be incomplete.")
                logger.warning(self.notices[-1])
                continue
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        if sources_failed == len(self.retrievers):
            raise RuntimeError("All configured paper sources failed")
        if sources_failed and not all_papers:
            raise RuntimeError("No papers were available while at least one source failed")
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            ranking_started = perf_counter()
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            logger.info(f"Ranking completed in {perf_counter() - ranking_started:.1f}s")
            if self.config.executor.max_paper_num != -1:
                reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            logger.info(f"Generating TLDR and affiliations for {len(reranked_papers)} selected papers...")
            generation_started = perf_counter()
            budget_notice = False
            for p in tqdm(reranked_papers):
                cache_key = state.paper_key(p, self.config)
                if state.restore_paper(cache_key, p):
                    logger.info(f"Restored completed summary for {p.url}")
                    continue
                budget = self.config.executor.get("generation_budget_minutes", 240) * 60
                if perf_counter() - started >= budget:
                    p.tldr, p.affiliations = p.abstract, None
                    p.generation_status, p.evidence_scope = "abstract_fallback", "abstract_only"
                    if not budget_notice:
                        self.notices.append("The processing time budget was reached; remaining selected papers retain their original abstracts. 部分入选论文保留原始摘要，未冒充模型总结。")
                        budget_notice = True
                    continue
                if self.config.executor.get("fetch_full_text", True):
                    try:
                        self.retrievers[p.source].enrich_paper(p)
                    except Exception as exc:
                        logger.warning(f"Full-text enrichment failed for {p.url}; using the abstract: {exc}")
                try:
                    if (self.config.llm.get("backend", "api") == "local"
                            and self.config.executor.get("combine_llm_requests", True)):
                        p.generate_insights(self.openai_client, self.config.llm)
                    else:
                        p.generate_tldr(self.openai_client, self.config.llm)
                        p.generate_affiliations(self.openai_client, self.config.llm)
                except Exception as exc:
                    logger.warning(f"Paper generation failed for {p.url}: {type(exc).__name__}; continuing")
                    p.tldr, p.affiliations, p.generation_status = p.abstract, None, "abstract_fallback"
                state.save_paper(cache_key, p)
            logger.info(f"Paper enrichment and generation completed in {perf_counter() - generation_started:.1f}s")
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. No email will be sent.")
            record_delivery(self.config.executor.get("report_dir"), "", "empty_skipped", [], self.notices)
            return
        logger.info("Sending email...")
        self._deliver(reranked_papers, state)
        logger.info(f"Email sent successfully; total runtime {perf_counter() - started:.1f}s")
