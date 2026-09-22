"""Conversational requests should reach search as focused, contextual queries."""
import webagent
import pytest


@pytest.mark.parametrize('path', ['selected', 'refinement', 'deep_think', 'fallback'])
def test_mothman_request_cannot_search_or_cite_john_lindsay(monkeypatch, path):
    prompt = 'tell me about the history of the moth man'
    wrong_query = 'John Lindsay history'
    webagent.context.assistant_convo = [
        {'role': 'user', 'content': 'Tell me about John Lindsay'},
        {'role': 'assistant', 'content': 'John Lindsay was a mayor.'},
    ]
    monkeypatch.setattr(webagent, '_subscription_bypass', lambda _: None)
    monkeypatch.setattr(webagent, '_try_live_lookup_bypasses', lambda _: None)
    monkeypatch.setattr(webagent, '_select_tool_actions', lambda _: [
        {'tool': 'web.search', 'arguments': {'query': wrong_query}},
    ] if path == 'selected' else [])
    monkeypatch.setattr(webagent, '_deep_think_research_plan', lambda _: [wrong_query])
    monkeypatch.setattr(webagent, '_fallback_research_query', lambda *a, **kw: wrong_query)
    monkeypatch.setattr(webagent, 'requires_current_web_verification', lambda _: path == 'fallback')
    monkeypatch.setattr(webagent, '_research_action', lambda *a: (
        {'action': 'answer'} if path == 'fallback' else {'action': 'search', 'query': wrong_query}
    ))
    webagent.context.deep_think_mode = path == 'deep_think'
    searched = []
    def execute(name, **kwargs):
        searched.append(kwargs['query'])
        return [
            {'title': 'John Lindsay history', 'content': 'Mayor of New York',
             'url': 'https://example.org/lindsay'},
            {'title': 'Mothman history', 'content': 'Folklore and reported sightings',
             'url': 'https://example.org/mothman'},
        ]
    monkeypatch.setattr(webagent.tool_registry, 'execute', execute)
    evidence = webagent.model_directed_web_research(prompt)
    assert searched == [prompt]
    assert [item['url'] for item in evidence] == ['https://example.org/mothman']


def test_query_guard_accepts_mothman_spacing_and_name_corrections():
    assert webagent._validated_research_query('history of the moth man', 'Mothman origins') == 'Mothman origins'
    assert webagent._validated_research_query('Alister Crawley', 'Aleister Crowley biography') == 'Aleister Crowley biography'


def test_fallback_rewrites_followup_using_conversation(monkeypatch):
    webagent.context.assistant_convo = [
        {"role": "user", "content": "Tell me about tommyknockers."},
        {"role": "assistant", "content": "They feature in mining folklore."},
    ]
    captured = []
    query = "tommyknockers coal mines nocturnal folklore"
    def chat(**kwargs):
        captured.append(kwargs["messages"][0]["content"])
        return {"message": {"content": query}}
    monkeypatch.setattr(webagent, "ollama", object())
    monkeypatch.setattr(webagent, "model_chat", chat)
    prompt = "they supposedly live in coal mines and come out at night"
    assert webagent._fallback_research_query(prompt, []) == query
    assert "tommyknockers" in captured[0]
    assert prompt in captured[0]


def test_verification_preserves_planner_query_even_without_results(monkeypatch):
    prompt = "double check. they supposedly live in the coal mines and come out at night. they are a paranormal critter."
    query = "tommyknockers coal mines nocturnal folklore"
    monkeypatch.setattr(webagent, "_subscription_bypass", lambda _: None)
    monkeypatch.setattr(webagent, "_try_live_lookup_bypasses", lambda _: None)
    monkeypatch.setattr(webagent, "_select_tool_actions", lambda _: [])
    monkeypatch.setattr(webagent, "_research_action", lambda *args: {"action": "search", "query": query})
    def unexpected_fallback(*args):
        raise AssertionError("A valid planner query must not be overwritten")
    monkeypatch.setattr(webagent, "_fallback_research_query", unexpected_fallback)
    searched = []
    def execute(name, **kwargs):
        assert name == "web.search"
        searched.append(kwargs["query"])
        return []
    monkeypatch.setattr(webagent.tool_registry, "execute", execute)
    assert webagent.requires_current_web_verification(prompt)
    assert webagent.model_directed_web_research(prompt) == []
    assert searched == [query]
