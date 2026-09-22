"""Local notes must not end fresh-fact research or become unrelated citations."""
import pytest

import webagent
from core.topic_guard import filter_web_results


@pytest.mark.parametrize('query', ['Alister Crawley', 'alister crawley residence', 'Aleister Crowley'])
def test_search_accepts_correctly_spelled_name(query, monkeypatch):
    source = {"title": "Aleister Crowley", "content": "His life and homes.",
              "url": "https://example.org/crowley"}
    monkeypatch.setattr(webagent, 'search_searx', lambda _: [source])
    results = webagent.search_web(query)
    assert results[0]['url'] == source['url']
    # The later evidence filter must also accept the corrected name.
    assert filter_web_results(query, results) == results


def test_relevance_does_not_reuse_one_fuzzy_word():
    assert filter_web_results('alister aleister', [
        {'title': 'Aleister', 'content': 'Unrelated page'},
    ]) == []


def test_filter_rejection_is_distinct_from_provider_failure(monkeypatch, capsys):
    monkeypatch.setattr(webagent, 'search_searx', lambda _: [
        {'title': 'Golden Corral', 'content': 'Buffet restaurant', 'url': 'https://example.org'},
    ])
    webagent.search_web('Golden Dawn')
    output = capsys.readouterr().out
    assert 'none passed the topic relevance filter' in output
    assert 'sources unavailable' not in output


def test_empty_provider_results_report_unavailability(monkeypatch, capsys):
    monkeypatch.setattr(webagent, 'search_searx', lambda _: [])
    webagent.search_web('Golden Dawn')
    assert 'sources unavailable or returned no results' in capsys.readouterr().out


def test_golden_dawn_rejects_unrelated_provider_hits():
    results = [
        {"title": "Cómo obtener ayuda en Windows", "content": "Soporte Microsoft"},
        {"title": "Golden Corral", "content": "America's buffet restaurant"},
        {"title": "Golden 1 Credit Union", "content": "Banking services"},
        {"title": "Golden", "content": "Official music video"},
        {"title": "Hermetic Order of the Golden Dawn", "content": "Ceremonial magic and cipher manuscripts"},
    ]
    assert filter_web_results("Golden Dawn", results) == results[-1:]
    assert filter_web_results("lets talk about some of the sciences of the hermetic order of the golden dawn", results) == results[-1:]


def test_selected_search_does_not_save_or_attribute_off_topic_results(monkeypatch):
    monkeypatch.setattr(webagent.tool_registry, "execute", lambda *a, **kw: [
        {"title": "Golden Corral", "content": "Buffet restaurant", "url": "https://example.com"},
    ])
    assert webagent._execute_research_tool_action(
        {"tool": "web.search", "arguments": {"query": "Golden Dawn"}}, "Golden Dawn"
    ) == []


@pytest.fixture
def local_notes_only(monkeypatch):
    monkeypatch.setattr(webagent, '_subscription_bypass', lambda prompt: None)
    monkeypatch.setattr(webagent, '_try_live_lookup_bypasses', lambda prompt: None)
    monkeypatch.setattr(webagent, '_select_tool_actions', lambda prompt: [
        {'tool': 'knowledge.search', 'arguments': {'topic': 'America'}},
    ])
    monkeypatch.setattr(webagent, '_research_action', lambda *args: {'action': 'answer'})
    searched = []
    def execute(name, **kwargs):
        if name == 'knowledge.search':
            return [('us_wealth_gap.txt', 'America has wealth gaps between workers and CEOs.')]
        assert name == 'web.search'
        searched.append(kwargs['query'])
        return []
    monkeypatch.setattr(webagent.tool_registry, 'execute', execute)
    return searched


@pytest.mark.parametrize('prompt', ['what is the population of america?', 'How many people live in America?'])
def test_population_questions_require_verification(prompt):
    assert webagent.requires_current_web_verification(prompt)


def test_population_research_does_not_stop_at_wealth_gap_notes(local_notes_only, monkeypatch):
    prompt = 'what is the population of america?'
    evidence = webagent.model_directed_web_research(prompt)
    assert local_notes_only == [prompt]
    assert evidence == []  # unrelated local notes aren't shown as Sources


def test_population_research_uses_new_web_evidence(local_notes_only, monkeypatch):
    original_execute = webagent.tool_registry.execute
    def execute(name, **kwargs):
        if name == 'web.search':
            return [{'title': 'Population estimate', 'url': 'https://www.census.gov/example',
                     'content': 'United States population estimate as of the stated date.'}]
        return original_execute(name, **kwargs)
    monkeypatch.setattr(webagent.tool_registry, 'execute', execute)
    evidence = webagent.model_directed_web_research('what is the population of america?')
    assert evidence
    assert all(item['search_provider'] != 'knowledge-base' for item in evidence)
    assert all('wealth' not in item['content'] for item in evidence)


def test_local_only_hits_are_checked_for_sufficiency(local_notes_only, monkeypatch):
    consulted = []
    def refine(prompt, evidence, searches_used):
        consulted.extend(evidence)
        return {'action': 'answer'}
    monkeypatch.setattr(webagent, '_research_action', refine)
    evidence = webagent.model_directed_web_research('explain wealth gaps in America')
    assert consulted
    assert evidence[0]['search_provider'] == 'knowledge-base'
    assert local_notes_only == []


def test_empty_evidence_prompt_explains_failure_to_verify():
    prompt = webagent.enhance_conversation_with_search('what is the population of america?', [])
    assert "couldn't verify the requested fact" in prompt
    assert 'ignore evidence about a different topic' in prompt


def test_chat_uses_saved_passages_without_enabling_web(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.record_to_knowledge_base('stoicism.md', 'Stoicism teaches acceptance and impermanence.')
    monkeypatch.setattr(webagent, '_select_tool_action', lambda prompt: {'tool': None})
    seen = []
    webagent.chat_response('explain stoicism', on_sources=seen.extend)
    assert seen and seen[0]['search_provider'] == 'knowledge-base'
    assert webagent.context.assistant_convo[-1]['sources'] == seen
    assert not webagent.context.web_search_mode


def test_chat_does_not_ground_current_population_in_saved_estimates(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.record_to_knowledge_base('census.md', 'United States population was 331 million in 2020.')
    monkeypatch.setattr(webagent, '_select_tool_action', lambda prompt: {'tool': None})
    seen = []
    webagent.chat_response('what is the population of America?', on_sources=seen.extend)
    assert not seen
