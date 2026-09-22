from concurrent.futures import Future
from core.unsupervised_learning import UnsupervisedLearning


class Pool:
    def __init__(self):
        self.futures = []

    def submit(self, *args):
        future = Future()
        self.futures.append(future)
        return future

    def shutdown(self, **kwargs):
        pass


def test_toggle_drains_whole_wave_before_restart(tmp_path):
    learner = UnsupervisedLearning(tmp_path)
    learner.pool.shutdown()
    learner.pool = Pool()
    learner.set_enabled(True)
    assert len(learner.pending) == 1
    assert learner.workers == 4
    learner.set_enabled(False)
    assert not learner.pool.futures[0].cancelled()
    learner.set_enabled(True)
    assert len(learner.pool.futures) == 1
    learner.set_enabled(False)
    learner.pool.futures[0].set_result({'tasks': [{'research': {'saved_sources': 1}}]})
    learner.tick()
    assert not learner.pending
    learner.set_enabled(True)
    assert len(learner.pool.futures) == 2
    learner.shutdown()


def test_failure_backs_off(tmp_path):
    learner = UnsupervisedLearning(tmp_path)
    learner.pool.shutdown()
    learner.pool = Pool()
    learner.set_enabled(True)
    learner.pool.futures[0].set_exception(RuntimeError('offline'))
    learner.tick()
    assert not learner.pending
    assert learner.recent == [{'error': 'offline'}]
    learner.shutdown()


def test_scoped_historian_leaves_other_tasks_untouched(tmp_path, monkeypatch):
    import webagent
    monkeypatch.setattr(webagent, '_historian_classify_topics', lambda titles, **kw: ['science'] * len(titles))
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    (first / 'note.txt').write_text('research findings')
    (second / 'note.txt').write_text('research in progress')
    result = webagent.historian(knowledge_root=first)
    assert result['files_sorted'] == 1
    assert (first / 'science/note.txt').exists()
    assert (second / 'note.txt').read_text() == 'research in progress'


def test_task_publishes_only_after_historian(tmp_path, monkeypatch):
    import webagent
    from core.unsupervised_learning import run_task
    from core.knowledge_maintenance import atomic_json
    query = 'How do coral reefs recover after bleaching?'
    def research(root, **kwargs):
        atomic_json(root / 'knowledge_base/web_evidence/source.json', {'content': 'evidence'})
        return {'saved_sources': 1, 'errors': []}
    monkeypatch.setattr('core.unsupervised_learning.run_research', research)
    def cleanup(knowledge_root):
        assert (knowledge_root / 'web_evidence/source.json').exists()
        assert not (tmp_path / 'knowledge_base/unsupervised_learning').exists()
        return {'files_sorted': 0}
    monkeypatch.setattr(webagent, 'historian', cleanup)
    report = run_task(tmp_path, chat=lambda prompt: {'query': query})
    from pathlib import Path
    assert (Path(report['knowledge']) / 'web_evidence/source.json').exists()
    assert report['question'] == query


def test_wikipedia_preferred_and_failed_pages_skipped():
    from core.unsupervised_learning import wikipedia_first_search
    queries, fetched = [], []
    def search(query):
        queries.append(query)
        return [{'url': 'https://example.org/topic'}, {'url': 'https://en.wikipedia.org/wiki/Topic'}]
    def fetch(url):
        fetched.append(url)
        return 'Article text. ' * 20 if 'wikipedia.org' in url else ''
    results = wikipedia_first_search('coral reef recovery', search=search, fetch=fetch)
    assert queries[0].startswith('site:en.wikipedia.org ')
    assert fetched[0] == 'https://en.wikipedia.org/wiki/Topic'
    assert len(results) == 1
    assert results[0]['evidence_kind'] == 'page_extract'


def test_historian_waits_for_entire_wave(tmp_path, monkeypatch):
    import threading
    import time
    release = threading.Event()
    started = threading.Barrier(4)
    calls = []
    def task(root, defer_cleanup):
        assert defer_cleanup
        started.wait(timeout=3)
        release.wait(timeout=3)
        return {'research': {'saved_sources': 1}}
    def finish(root, wave, reports):
        calls.append(len(reports))
        return {'tasks': reports}
    monkeypatch.setattr('core.unsupervised_learning.finish_wave', finish)
    learner = UnsupervisedLearning(tmp_path, workers=3, task=task)
    learner.set_enabled(True)
    started.wait(timeout=3)
    learner.set_enabled(False)
    assert not calls
    release.set()
    for future in learner.pending:
        future.result(timeout=3)
    learner.tick()
    assert calls == [3]
    assert not learner.pending
    assert learner.wave_number == 1
    learner.shutdown()


def test_partial_wave_automatically_restarts_after_countdown(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr('core.unsupervised_learning.time.monotonic', lambda: now[0])
    learner = UnsupervisedLearning(tmp_path)
    learner.pool.shutdown()
    learner.pool = Pool()
    learner.set_enabled(True)
    learner.pool.futures[0].set_result({'tasks': [
        {'error': 'Model did not select a novel public research question'},
        {'research': {'saved_sources': 4, 'saved_answers': 0}},
    ]})
    learner.tick()
    assert 'Wave 2 starts in 15s' in learner.status_text()
    now[0] = 114
    learner.tick()
    assert len(learner.pool.futures) == 1
    assert 'starts in 1s' in learner.status_text()
    now[0] = 115
    learner.tick()
    assert len(learner.pool.futures) == 2
    assert learner.wave_number == 2
    assert 'researching' in learner.status_text()
    learner.shutdown()


def test_output_explains_missing_and_repaired_answers(tmp_path):
    learner = UnsupervisedLearning(tmp_path)
    learner.recent = [{'tasks': [{'question': 'Coral recovery', 'research': {
        'saved_sources': 4, 'saved_answers': 0,
        'topics': [{'answer': {'status': 'not_saved', 'reason': 'Answer is empty.'}}],
    }}, {'question': 'Ocean currents', 'research': {
        'saved_sources': 3, 'saved_answers': 1,
        'topics': [{'answer': {'status': 'repaired'}}],
    }}]}]
    text = learner.output_text()
    assert 'Answer not saved: Answer is empty.' in text
    assert 'sources were retained' in text
    assert 'Answer saved after one repair attempt.' in text
    learner.shutdown()


def test_topic_selection_repairs_duplicate_and_long_question():
    from core.unsupervised_learning import select_topic
    prior = 'How do coral reefs recover after bleaching?'
    replies = iter([{'query': prior}, {'query': 'word ' * 100},
                    {'query': 'How do volcanic rocks record ancient magnetic fields?'}])
    prompts = []
    def chat(prompt):
        prompts.append(prompt)
        return next(replies)
    assert 'volcanic rocks' in select_topic(chat, [prior])
    assert 'repeats an already selected topic' in prompts[1]
    assert 'at most 220 characters' in prompts[2]


def test_topic_selection_failure_reports_reasons():
    import pytest
    from core.unsupervised_learning import select_topic
    calls = []
    def chat(prompt):
        calls.append(prompt)
        return {'topic': 'wrong field'}
    with pytest.raises(ValueError, match='after 3 attempts: Missing nonempty query'):
        select_topic(chat, [])
    assert len(calls) == 3


def test_repeating_model_uses_novel_public_fallbacks():
    from core.autonomous_research import public_query
    from core.knowledge_retrieval import terms
    from core.unsupervised_learning import select_topic
    prior = 'How do coral reefs recover after bleaching?'
    recent = [prior]
    calls = []
    def chat(prompt):
        calls.append(prompt)
        return {'query': prior}
    for _ in range(4):
        query = select_topic(chat, recent)
        assert public_query(query)
        assert terms(query) not in [terms(old) for old in recent]
        recent.append(query)
    assert len(calls) == 12


def test_fallback_pool_survives_full_recent_history():
    from core.unsupervised_learning import (
        select_topic, _FALLBACK_SUBJECTS, _FALLBACK_TEMPLATES,
    )
    from core.knowledge_retrieval import terms
    from core.autonomous_research import public_query
    candidates = [template.format(subject=subject)
                  for subject in _FALLBACK_SUBJECTS for template in _FALLBACK_TEMPLATES]
    assert all(public_query(query) for query in candidates)
    assert len({tuple(terms(query)) for query in candidates}) > 100
    recent = candidates[:100]
    query = select_topic(lambda prompt: {'query': recent[0]}, recent)
    assert query in candidates[100:]


def test_empty_wave_does_not_claim_saved_findings(tmp_path, monkeypatch):
    import webagent
    from core.unsupervised_learning import finish_wave
    def forbidden(**kwargs):
        raise AssertionError('Historian should not run without findings')
    monkeypatch.setattr(webagent, 'historian', forbidden)
    result = finish_wave(tmp_path, 'empty', [{'error': 'Topic selection failed'}])
    assert result['knowledge'] is None
    assert not (tmp_path / 'knowledge_base').exists()
    learner = UnsupervisedLearning(tmp_path)
    learner.recent = [result]
    assert 'No findings collected' in learner.output_text()
    assert 'findings saved' not in learner.output_text()
    learner.shutdown()


def test_search_activity_emitted_before_network_returns():
    from core.unsupervised_learning import wikipedia_first_search, _progress
    messages = []
    _progress.callback = messages.append
    def search(query):
        assert messages[-1] == 'Searching: ' + query
        return [{'url': 'https://en.wikipedia.org/wiki/Coral'}]
    def fetch(url):
        assert messages[-1] == 'Scraping: ' + url
        return 'Coral research text. ' * 20
    try:
        wikipedia_first_search('coral reefs', search=search, fetch=fetch)
        assert any(message.startswith('Extracted ') for message in messages)
    finally:
        del _progress.callback
