from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.digest_state import DigestState
from zotero_arxiv_daily.evidence import paper_evidence
from zotero_arxiv_daily.executor import Executor
from zotero_arxiv_daily.protocol import CorpusPaper


@pytest.mark.parametrize("heading", [lambda name: '\\section{' + name + '}', lambda name: '## ' + name, lambda name: '3 ' + name])
def test_long_introduction_does_not_hide_results_or_limitations(heading):
    text = heading("Introduction") + '\n' + 'background ' * 10000
    text += '\n' + heading("Method") + '\nACTION_POLICY\n'
    text += heading("Experiments") + '\nREAL_ROBOT_RESULTS\n'
    text += heading("Limitations") + '\nONLY_TWO_ROBOTS\n'
    text += heading("Conclusion") + '\nNO_GENERALIZATION_CLAIM\n'
    prompt, scope = paper_evidence("VLA", "Abstract", text, lambda value, limit: value[:limit], 4000)
    assert scope == "section_excerpts"
    assert all(value in prompt for value in ("ACTION_POLICY", "REAL_ROBOT_RESULTS", "ONLY_TWO_ROBOTS", "NO_GENERALIZATION_CLAIM"))
    assert len(prompt) <= 4000


def test_unstructured_body_includes_its_actual_end_and_abstract_only_uses_full_budget():
    prompt, scope = paper_evidence("Title", "Abstract", 'background ' * 10000 + 'FINAL_FINDING',
                                  lambda value, limit: value[:limit], 4000)
    assert 'FINAL_FINDING' in prompt
    assert scope == 'body_excerpts'
    prompt, scope = paper_evidence("Title", 'a' * 2500 + 'ABSTRACT_END', None,
                                  lambda value, limit: value[:limit], 4000)
    assert 'ABSTRACT_END' in prompt
    assert scope == 'abstract_only'


def test_bad_json_is_retried_and_is_not_saved_as_a_completed_summary(config, monkeypatch, tmp_path):
    config.llm.backend = "local"
    config.llm.summary_attempts = 2
    monkeypatch.setattr("zotero_arxiv_daily.protocol.sleep", lambda _: None)
    replies = iter(['bad json', '{"tldr":"Supported summary", "affiliations":[]}'])
    client = SimpleNamespace(truncate_prompt=lambda text, limit: text[:limit], generate=lambda *a, **kw: next(replies))
    paper = make_sample_paper()
    assert paper.generate_insights(client, config.llm) == "Supported summary"
    assert paper.generation_status == "generated"
    state = DigestState(tmp_path)
    paper.generation_status = "abstract_fallback"
    state.save_paper("failed", paper)
    assert state.get("failed") is None
    state.close()


def make_executor(config, papers, client):
    executor = Executor.__new__(Executor)
    executor.config = config
    executor.openai_client = client
    executor.fetch_zotero_corpus = lambda: [CorpusPaper("Private library title", "PRIVATE_LIBRARY_TEXT", datetime(2026, 1, 1), [])]
    executor.filter_corpus = lambda corpus: corpus
    executor.retrievers = {"arxiv": SimpleNamespace(retrieve_papers=lambda: papers, enrich_paper=lambda p: p)}

    def rerank(candidates, corpus):
        for paper in candidates:
            paper.score = 7.0
        return candidates
    executor.reranker = SimpleNamespace(rerank=rerank)
    return executor


def test_smtp_failure_resumes_summaries_and_scheduled_retry_skips_after_acceptance(config, tmp_path, monkeypatch):
    config.llm.backend = "local"
    config.executor.state_dir = str(tmp_path / 'state')
    config.executor.report_dir = str(tmp_path / 'report')
    calls = []
    client = SimpleNamespace(truncate_prompt=lambda text, limit: text[:limit],
                             generate=lambda *a, **kw: calls.append(1) or 'Supported summary')
    attempts = []
    def send(cfg, html):
        attempts.append(html)
        if len(attempts) == 1:
            raise OSError("Connection failed")
    monkeypatch.setattr("zotero_arxiv_daily.executor.send_email", send)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    for index in range(2):
        executor = make_executor(config, [make_sample_paper(title="Public paper", tldr=None, full_text=None)], client)
        if index == 0:
            with pytest.raises(OSError):
                executor.run()
            assert json.loads((tmp_path / 'report' / 'status.json').read_text(encoding="utf-8"))["status"] == "smtp_failed_or_unconfirmed"
        else:
            executor.run()
    assert len(calls) == 1, "A retry must reuse the completed summary even after an SMTP failure"
    assert len(attempts) == 2
    executor.fetch_zotero_corpus = lambda: pytest.fail("Already delivered; do not refetch the library")
    executor.run()
    assert len(attempts) == 2
    raw_state = (tmp_path / 'state' / 'state.sqlite3').read_bytes()
    assert b'PRIVATE_LIBRARY_TEXT' not in raw_state
    assert b'fake-zotero-key' not in raw_state
    assert b'test@example.com' not in raw_state


def test_one_bad_paper_does_not_cancel_the_other_papers(config, monkeypatch):
    config.llm.backend = "local"
    papers = [make_sample_paper(title="broken"), make_sample_paper(title="good")]
    def generate(self, *args):
        if self.title == "broken":
            raise RuntimeError("Unexpected per-paper problem")
        self.tldr, self.generation_status = "Completed", "generated"
    monkeypatch.setattr(type(papers[0]), "generate_tldr", generate)
    sent = []
    monkeypatch.setattr("zotero_arxiv_daily.executor.send_email", lambda cfg, html: sent.append(html))
    make_executor(config, papers, None).run()
    assert len(sent) == 1 and "Completed" in sent[0]
    assert "showing the original abstract" in sent[0]


def test_source_outage_sends_failure_notice_not_a_false_empty_day(config, monkeypatch, tmp_path):
    config.executor.report_dir = str(tmp_path)
    executor = make_executor(config, [], None)
    def failed():
        raise TimeoutError("External service unavailable")
    executor.retrievers['arxiv'].retrieve_papers = failed
    sent = []
    monkeypatch.setattr("zotero_arxiv_daily.executor.send_email", lambda cfg, html: sent.append(html))
    with pytest.raises(RuntimeError, match="All configured"):
        executor.run()
    assert len(sent) == 1
    assert "No Papers Today" not in sent[0]
    assert json.loads((tmp_path / 'status.json').read_text(encoding="utf-8"))["status"] == "failure_notice_sent"


def test_changed_summary_settings_invalidate_saved_output(config, tmp_path):
    state = DigestState(tmp_path)
    paper = make_sample_paper(tldr="Done")
    paper.generation_status = "generated"
    key = state.paper_key(paper, config)
    state.save_paper(key, paper)
    config.llm.local.input_tokens += 1
    assert not state.restore_paper(state.paper_key(paper, config), paper)
    state.close()


def test_time_budget_still_delivers_all_twenty_selected_papers(config, monkeypatch):
    config.llm.backend = "local"
    config.executor.generation_budget_minutes = 0
    papers = [make_sample_paper(title=f"Selected paper {index}", url=f"https://arxiv.org/abs/test-{index}") for index in range(20)]
    executor = make_executor(config, papers, None)
    executor.retrievers['arxiv'].enrich_paper = lambda paper: pytest.fail("Deadline reached; do not start optional extraction")
    sent = []
    monkeypatch.setattr("zotero_arxiv_daily.executor.send_email", lambda cfg, html: sent.append(html))
    executor.run()
    assert len(sent) == 1
    assert all(paper.title in sent[0] for paper in papers)
    assert all(paper.generation_status == "abstract_fallback" for paper in papers)
    assert "processing time budget was reached" in sent[0]
