import json
from core.knowledge_retrieval import KnowledgeIndex
from core.chat_evaluation import evaluate, source_removal_diagnostics


def test_retrieves_late_passage_and_paraphrases(tmp_path):
    (tmp_path/'population.md').write_text('Bread recipes. '*450 + 'The population of the United States was 331 million in the 2020 census.')
    (tmp_path/'wealth.md').write_text('America wealth gaps and corporate salaries of 10 million.')
    index = KnowledgeIndex(tmp_path)
    report = evaluate(index, [
        {'query': 'what is the population of america', 'expected_sources': ['population.md'], 'excluded_sources': ['wealth.md']},
        {'query': 'how many residents in the USA', 'expected_sources': ['population.md'], 'excluded_sources': ['wealth.md']},
    ])
    assert report['passed'] == 2
    hit = index.search('population america')[0][1]
    assert '331 million' in hit
    assert hit.metadata['offset'] > 2000
    assert hit.metadata['verification_status'] == 'unverified'


def test_incremental_updates_duplicates_and_deletions(tmp_path):
    a = tmp_path/'a.md'; b = tmp_path/'b.md'
    a.write_text('Stoicism teaches impermanence.'); b.write_text(a.read_text())
    index = KnowledgeIndex(tmp_path)
    assert len(index.search('stoicism')) == 1
    cached = index.files['a.md'][1]
    index.search('stoicism')
    assert index.files['a.md'][1] is cached
    a.write_text('Baking sourdough bread.'); b.unlink()
    assert not index.search('stoicism')
    assert index.search('sourdough')[0][0] == 'a.md'


def test_provenance_original_dates_and_binary_safety(tmp_path):
    (tmp_path/'capture.json').write_text(json.dumps({'content': 'US population was 331 million.', 'url': 'https://example.org/census', 'captured_at': '2020-01-01', 'title': 'Census'}))
    (tmp_path/'bad.md').write_bytes(b'\xff\xfe')
    (tmp_path/'conversation.json').write_text(json.dumps([{'role': 'assistant', 'content': 'Population is 9 billion.'}]))
    hit = KnowledgeIndex(tmp_path).search('population US')[0][1]
    assert hit.metadata['captured_at'] == '2020-01-01'
    assert hit.metadata['url'] == 'https://example.org/census'
    assert hit.metadata['origin'] == 'saved-web'


def test_removal_diagnostics_do_not_modify_files(tmp_path):
    (tmp_path/'a.md').write_text('Stoicism teaches impermanence.')
    index = KnowledgeIndex(tmp_path)
    result = source_removal_diagnostics(index, 'stoicism')
    assert result['removals'][0]['remaining_sources'] == []
    assert (tmp_path/'a.md').exists()
    assert index.search('stoicism')


def test_invalid_regex_is_literal_query(tmp_path):
    (tmp_path/'a.md').write_text('Stoicism teaches impermanence.')
    assert KnowledgeIndex(tmp_path).search('[stoicism')


def test_embedding_failure_preserves_keyword_results(tmp_path, monkeypatch):
    import ollama
    monkeypatch.setenv('GNOSIS_EMBEDDING_MODEL', 'local-embedding')
    class FailingClient:
        def __init__(self, **kwargs): pass
        def embed(self, **kwargs): raise RuntimeError('offline')
    monkeypatch.setattr(ollama, 'Client', FailingClient)
    (tmp_path/'a.md').write_text('Stoicism teaches impermanence.')
    hit = KnowledgeIndex(tmp_path).search('stoicism')[0][1]
    assert hit.metadata['embedding_status'] == 'RuntimeError'


def test_semantic_paraphrase_and_vector_cache(tmp_path, monkeypatch):
    import ollama
    from types import SimpleNamespace
    monkeypatch.setenv('GNOSIS_EMBEDDING_MODEL', 'local-embedding')
    calls = []
    class Client:
        def __init__(self, **kwargs): assert kwargs['host'].startswith('http://127.0.0.1')
        def embed(self, model, input):
            calls.append(input)
            return SimpleNamespace(embeddings=[[1., 0.] for _ in (input if isinstance(input, list) else [input])])
    monkeypatch.setattr(ollama, 'Client', Client)
    (tmp_path/'a.md').write_text('Stoicism teaches impermanence.')
    index = KnowledgeIndex(tmp_path)
    assert index.search('philosophical transience')
    index.search('philosophical transience')
    assert len([call for call in calls if isinstance(call, list)]) == 1


def test_country_disambiguation(tmp_path):
    (tmp_path/'uk.md').write_text('United Kingdom population was 67 million.')
    (tmp_path/'usa.md').write_text('United States population was 331 million.')
    names = [name for name, _ in KnowledgeIndex(tmp_path).search('population America')]
    assert names == ['usa.md']


def test_fact_reaches_first_prompt_sentences(tmp_path):
    import webagent
    (tmp_path/'census.md').write_text('Bread recipes. '*450 + 'United States population was 331 million in the 2020 census.')
    hits = KnowledgeIndex(tmp_path).search('population America')
    evidence = webagent._knowledge_search_evidence('population America', hits)
    prompt = webagent.enhance_conversation_with_search('population America', evidence)
    assert '331 million' in prompt


def test_preferences_can_enable_and_disable_embeddings(tmp_path, monkeypatch):
    from core.knowledge_retrieval import embedding_model, save_embedding_model
    monkeypatch.delenv('GNOSIS_EMBEDDING_MODEL', raising=False)
    save_embedding_model(tmp_path, 'nomic-embed-text')
    assert embedding_model(tmp_path) == 'nomic-embed-text'
    save_embedding_model(tmp_path, '')
    assert embedding_model(tmp_path) == ''


def test_population_rejects_foreign_policy_and_wrong_country_counts(tmp_path):
    (tmp_path/'foreign.md').write_text('16 hours ago: Leading America foreign policy to protect the American people.')
    (tmp_path/'iran.md').write_text('Iran has a population of 92 million. The United States has economic sanctions on Iran.')
    (tmp_path/'conversation.md').write_text('User: what is the population of America? Assistant: The provided evidence discusses wealth gaps. confidence 58/100')
    (tmp_path/'census.md').write_text('The United States population was 331 million in 2020.')
    assert [name for name, _ in KnowledgeIndex(tmp_path).search('population America')] == ['census.md']
