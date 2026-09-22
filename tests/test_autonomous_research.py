from datetime import datetime, timezone, timedelta
import json

from core import autonomous_research as ar
from core.knowledge_maintenance import read_json, atomic_json
from core.knowledge_retrieval import KnowledgeIndex

NOW = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
QUESTION = 'How does Python memory garbage collection work?'
A = 'Python memory garbage collection detects unreachable objects and releases their memory.'
B = 'Python memory garbage collection also detects reference cycles using a cyclic collector.'


def seed(root):
    return ar.record_gap(root, QUESTION, 'uncertain_answer')


def search(query):
    return [{'url': 'https://docs.python.org/gc', 'content': A},
            {'url': 'https://example.org/python', 'content': B}]


def chat(prompt):
    if prompt.startswith('Convert'):
        return {'researchable': True, 'query': 'Python memory garbage collection'}
    return {'addresses_question': True, 'contradiction': False, 'answer': A + ' ' + B,
            'citations': [{'source': 0, 'quote': A}, {'source': 1, 'quote': B}], 'remaining_question': ''}


def test_learning_saves_retrievable_sources_and_closes_gap(tmp_path):
    key = seed(tmp_path)
    result = ar.run_research(tmp_path, chat=chat, search=search, now=NOW)
    assert result['supported'] == 1 and result['saved_sources'] == 2
    assert read_json(tmp_path/'knowledge_state/research_queue.json', {})['gaps'][key]['status'] == 'supported'
    assert KnowledgeIndex(tmp_path/'knowledge_base').search(QUESTION)
    assert ar.run_research(tmp_path, chat=chat, search=search, now=NOW)['attempted'] == 0


def test_fabricated_quotes_cannot_close_gap(tmp_path):
    seed(tmp_path)
    def wrong(prompt):
        reply = chat(prompt)
        if 'citations' in reply:
            reply['citations'][0]['quote'] = 'This is an invented quotation not found in source text.'
        return reply
    assert ar.run_research(tmp_path, chat=wrong, search=search, now=NOW)['supported'] == 0


def test_retries_back_off_and_exhaust_without_fake_evidence(tmp_path):
    key = seed(tmp_path)
    assert ar.run_research(tmp_path, chat=chat, search=lambda q: [], now=NOW)['partial'] == 1
    assert ar.run_research(tmp_path, chat=chat, search=search, now=NOW)['attempted'] == 0
    ar.run_research(tmp_path, chat=chat, search=lambda q: [], now=NOW+timedelta(days=1))
    ar.run_research(tmp_path, chat=chat, search=lambda q: [], now=NOW+timedelta(days=3))
    assert read_json(tmp_path/'knowledge_state/research_queue.json', {})['gaps'][key]['status'] == 'exhausted'
    assert not list((tmp_path/'knowledge_base').rglob('*.json'))


def test_daily_budget_applies_across_invocations_and_reopened_gaps(tmp_path):
    for i in range(5):
        ar.record_gap(tmp_path, f'Explain Python memory collection variant {i}', 'missing_evidence')
    assert ar.run_research(tmp_path, chat=chat, search=lambda q: [], now=NOW)['attempted'] == 3
    assert ar.run_research(tmp_path, chat=chat, search=search, now=NOW)['attempted'] == 0


def test_private_query_never_leaves_machine(tmp_path):
    seed(tmp_path)
    def private(prompt):
        return {'researchable': True, 'query': 'research password for alice@example.com'}
    result = ar.run_research(tmp_path, chat=private, search=lambda q: (_ for _ in ()).throw(AssertionError('network')), now=NOW)
    assert result['topics'][0]['status'] == 'needs_review'
    assert not result['errors']


def test_capture_and_backfill_are_idempotent(tmp_path):
    activity = tmp_path/'activity'
    activity.mkdir()
    row = {'event': 'TASK_COMPLETED', 'timestamp': '2026-09-20T02:00:00', 'user_input': QUESTION, 'response': 'I cannot verify this.'}
    (activity/'log.jsonl').write_text(json.dumps(row)+'\n')
    assert ar.discover_gaps(tmp_path) == 1
    assert ar.discover_gaps(tmp_path) == 1
    gap = next(iter(read_json(tmp_path/'knowledge_state/research_queue.json', {})['gaps'].values()))
    assert gap['occurrences'] == 1


def test_same_host_or_contradictions_leave_gap_open(tmp_path):
    seed(tmp_path)
    def one_host(query):
        results = search(query)
        results[1]['url'] = 'https://docs.python.org/another'
        return results
    assert ar.run_research(tmp_path, chat=chat, search=one_host, now=NOW)['supported'] == 0


def test_disabled_research_does_no_work(tmp_path):
    atomic_json(tmp_path/'knowledge_state/research_settings.json', {'enabled': False})
    assert ar.run_research(tmp_path)['outcome'] == 'skipped'


def test_external_requests_require_endpoint_approval(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setattr(ar, 'search_public', lambda _: (_ for _ in ()).throw(AssertionError('unexpected network')))
    assert 'awaits approval' in ar.run_research(tmp_path, chat=chat)['reason']
    atomic_json(tmp_path/'knowledge_state/research_settings.json', {
        'allow_external_search': True, 'approved_search_endpoint': 'https://different.example/search'})
    assert 'awaits approval' in ar.run_research(tmp_path, chat=chat)['reason']


def test_local_preview_does_not_search_or_charge_budget(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setattr(ar, 'search_public', lambda _: (_ for _ in ()).throw(AssertionError('unexpected network')))
    assert ar.preview_research(tmp_path, chat=chat)['queries'][0]['query'] == 'Python memory garbage collection'
    state = read_json(tmp_path/'knowledge_state/research_queue.json', {})
    assert next(iter(state['gaps'].values()))['attempts'] == 0


def test_explicit_fact_check_gaps_are_discovered_once(tmp_path):
    atomic_json(tmp_path/'knowledge_base/fact_checks/check.json', {'query': QUESTION, 'fact_check': '[Unverified] Not enough evidence.'})
    assert ar.discover_gaps(tmp_path) == 1
    assert ar.discover_gaps(tmp_path) == 1


def test_new_stage_is_wired_into_nightly_before_study():
    import nightly
    names = [name for name, _ in nightly.STAGES]
    assert names.index('historian') < names.index('research') < names.index('study') < names.index('index')


def test_empty_live_search_is_not_hidden_by_offline_fallback(isolated_data_dir, monkeypatch):
    import webagent
    from core.activity_log import load_activity
    monkeypatch.setattr(webagent, 'search_searx', lambda q: [])
    monkeypatch.setattr(webagent, 'search_fallback', lambda q: [{'title': 'Offline', 'url': 'offline://context', 'content': 'Offline background'}])
    webagent.search_web(QUESTION)
    assert load_activity(event_name='SEARCH_COMPLETED')[-1]['live_result_count'] == 0


def test_daytime_batch_size_preserves_shared_daily_budget(tmp_path):
    for i in range(4):
        ar.record_gap(tmp_path, f'Explain Python garbage collection example {i}', 'missing_evidence')
    for _ in range(3):
        result = ar.run_research(tmp_path, chat=chat, search=lambda q: [], now=NOW, batch_size=1)
        assert result['attempted'] == 1
    assert ar.run_research(tmp_path, chat=chat, search=search, now=NOW)['attempted'] == 0


def test_answer_is_saved_and_retrieved_with_citations(tmp_path):
    seed(tmp_path)
    result = ar.run_research(tmp_path, chat=chat, search=search, now=NOW)
    assert result['saved_answers'] == 1
    answers = list((tmp_path / 'knowledge_base/research_answers').glob('*.json'))
    document = read_json(answers[0], {})
    assert document['answer'] == A + ' ' + B
    assert document['citations'][0]['url'] == 'https://docs.python.org/gc'
    matches = KnowledgeIndex(tmp_path / 'knowledge_base').search(QUESTION)
    synthesis = [p for _, p in matches if p.metadata['origin'] == 'research-synthesis']
    assert synthesis
    assert synthesis[0].metadata['verification_status'] == 'unverified'
    assert synthesis[0].metadata['citations']


def test_invalid_answer_not_published_but_sources_retained(tmp_path):
    seed(tmp_path)
    def invalid(prompt):
        response = chat(prompt)
        if 'citations' in response:
            response['citations'][0]['quote'] = 'invented evidence which is not in the scraped document'
        return response
    result = ar.run_research(tmp_path, chat=invalid, search=search, now=NOW)
    assert result['saved_answers'] == 0
    assert result['saved_sources'] == 2
    assert not list((tmp_path / 'knowledge_base/research_answers').glob('*.json'))


def test_published_wave_answer_reaches_chat_evidence(tmp_path, monkeypatch):
    import webagent
    from core import config
    from core.unsupervised_learning import finish_wave
    stage = tmp_path / 'knowledge_state/learning_tasks/test'
    seed(stage)
    result = ar.run_research(stage, chat=chat, search=search, now=NOW)
    # A long-lived chat index must discover the new wave without restarting.
    index = KnowledgeIndex(tmp_path / 'knowledge_base')
    assert not index.search(QUESTION)
    report = finish_wave(tmp_path, 'wave', [{'staging': str(stage / 'knowledge_base'), 'research': result}])
    assert report['knowledge']
    matches = index.search(QUESTION)
    evidence = webagent._knowledge_search_evidence(QUESTION, matches)
    answers = [e for e in evidence if e['provenance']['origin'] == 'research-synthesis']
    assert answers
    assert 'Python memory garbage collection' in answers[0]['content']
    assert answers[0]['provenance']['citations'][0]['url'] == 'https://docs.python.org/gc'
    assert not stage.exists()


def test_answer_repair_reuses_sources_and_saves_result(tmp_path):
    seed(tmp_path)
    prompts, searches = [], []
    def repair_chat(prompt):
        if prompt.startswith('Convert'):
            return chat(prompt)
        prompts.append(prompt)
        response = chat(prompt)
        if len(prompts) == 1:
            response['citations'][0]['quote'] = 'Quotation absent from the actual source document.'
        return response
    def counted_search(query):
        searches.append(query)
        return search(query)
    result = ar.run_research(tmp_path, chat=repair_chat, search=counted_search, now=NOW)
    assert result['saved_answers'] == 1
    assert len(prompts) == 2
    assert 'not an exact substring' in prompts[1]
    assert 'Previous response' in prompts[1]
    assert len(searches) == 2  # Existing bounded search/refinement, not repeated for repair.
    diagnostic = result['topics'][0]['answer']
    assert diagnostic['status'] == 'repaired'
    assert diagnostic['attempts'][1]['errors'] == []


def test_malformed_json_gets_one_repair(tmp_path):
    seed(tmp_path)
    calls = []
    def broken(prompt):
        if prompt.startswith('Convert'):
            return chat(prompt)
        calls.append(prompt)
        raise json.JSONDecodeError('Invalid JSON', '', 0)
    result = ar.run_research(tmp_path, chat=broken, search=search, now=NOW)
    assert len(calls) == 2
    assert result['saved_answers'] == 0 and result['saved_sources'] == 2
    assert 'JSONDecodeError' in result['topics'][0]['answer']['reason']
    findings = list((tmp_path / 'knowledge_state/research_findings').glob('*.json'))
    assert read_json(findings[0], {})['answer_diagnostic']['status'] == 'not_saved'


def test_valid_answer_does_not_call_repair(tmp_path):
    seed(tmp_path)
    calls = []
    def counted(prompt):
        calls.append(prompt)
        return chat(prompt)
    result = ar.run_research(tmp_path, chat=counted, search=search, now=NOW)
    assert result['saved_answers'] == 1
    assert len(calls) == 2  # Query planning plus synthesis.
    assert result['topics'][0]['answer']['status'] == 'saved'


def test_repair_respects_expired_budget(monkeypatch):
    now = [0]
    monkeypatch.setattr(ar.time, 'monotonic', lambda: now[0])
    def slow(prompt):
        now[0] = 20
        return {'answer': ''}
    answer, diagnostic = ar.synthesize_answer(slow, 'question', [], deadline=10)
    assert not answer
    assert diagnostic['reason'] == 'Synthesis time budget exhausted.'


def test_empty_answer_and_bad_source_have_specific_diagnostics():
    errors = ar.answer_validation_errors(
        {'answer': '', 'addresses_question': True, 'contradiction': False,
         'citations': [{'source': 4, 'quote': A}]}, [{'content': A}])
    assert any('empty' in error for error in errors)
    assert any('source index' in error for error in errors)
