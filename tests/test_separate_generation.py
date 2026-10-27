from types import SimpleNamespace

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.digest_state import DigestState
from zotero_arxiv_daily.evidence import author_evidence
from zotero_arxiv_daily.local_llm import LocalLLM


def test_institution_call_gets_its_own_input_and_schema(config, stub_local_llm):
    config.llm.backend = "local"
    paper = make_sample_paper(full_text='\\author{Alice, Stanford University}\\maketitle\n\\section{Method}\nBODY_ONLY_RESULT')
    client = LocalLLM(config.llm.local)
    paper.generate_tldr(client, config.llm)
    paper.generate_affiliations(client, config.llm)
    assert len(stub_local_llm.requests) == 2
    first, second = stub_local_llm.requests
    assert 'response_format' not in first
    assert second['response_format']['schema']['required'] == ['affiliations']
    assert 'Stanford University' in second['messages'][1]['content']
    assert 'BODY_ONLY_RESULT' not in second['messages'][1]['content']
    assert paper.generation_status == 'generated'
    assert paper.affiliations_status == 'generated'


def test_failed_institutions_preserve_summary_for_stage_only_retry(config, tmp_path):
    config.llm.backend = 'local'
    replies = iter(['Good summary', 'not json'])
    client = SimpleNamespace(truncate_prompt=lambda text, size: text[:size], generate=lambda *a, **kw: next(replies))
    paper = make_sample_paper()
    paper.generate_tldr(client, config.llm)
    paper.generate_affiliations(client, config.llm)
    assert paper.tldr == 'Good summary'
    assert paper.affiliations_status == 'failed'
    state = DigestState(tmp_path)
    key = state.paper_key(paper, config)
    state.save_paper(key, paper)
    resumed = make_sample_paper(tldr=None)
    assert not state.restore_paper(key, resumed)
    assert resumed.tldr == 'Good summary'
    assert resumed.generation_status == 'generated'
    resumed.generate_affiliations(SimpleNamespace(truncate_prompt=lambda text, size: text[:size],
                                                 generate=lambda *a, **kw: '{"affiliations":["Stanford University"]}'), config.llm)
    state.save_paper(key, resumed)
    assert state.restore_paper(key, make_sample_paper(tldr=None))
    state.close()


def test_pinned_upgrade_disables_thinking_through_the_model_template(config, stub_local_llm, monkeypatch):
    config.llm.local.revision = 'pinned-revision'
    config.llm.local.enable_thinking = False
    downloads = []
    monkeypatch.setattr('huggingface_hub.hf_hub_download', lambda **kwargs: downloads.append(kwargs) or 'downloaded.gguf')
    model = LocalLLM(config.llm.local).model
    assert downloads[0]['revision'] == 'pinned-revision'
    assert stub_local_llm.loads[0]['model_path'] == 'downloaded.gguf'
    assert stub_local_llm.templates[0]['template'].startswith('{% set enable_thinking = false %}')
    assert model.chat_handler == 'test-handler'


def test_author_region_does_not_take_institutions_from_the_abstract_or_body():
    text = 'Authors: A. Author. Stanford University.\nAbstract\nExperiments at an unrelated institution.'
    assert 'unrelated institution' not in author_evidence(text)
