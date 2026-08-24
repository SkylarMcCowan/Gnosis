"""Regression tests for _research_action (webagent.py:1251), including the
Phase 6 entity-resolution fix: the planner prompt must now explicitly tell
the model to resolve a correction to its full, correctly-spelled form
before writing a search query, instead of allowing it to search the user's
raw (possibly typo'd/fragmentary) correction text verbatim.
"""
import webagent


def test_returns_answer_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(webagent, "ollama", None)
    assert webagent._research_action("what is the topic?", [], 0) == {"action": "answer"}


def test_forwards_a_valid_search_action(monkeypatch):
    monkeypatch.setattr(
        webagent.agent_dialogue, "call_agent_json",
        lambda chat_fn, planner: {"action": "search", "query": "specific query", "reason": "why"},
    )
    action = webagent._research_action("what is the topic?", [], 0)
    assert action == {"action": "search", "query": "specific query", "reason": "why"}


def test_honors_a_valid_answer_decision(monkeypatch):
    monkeypatch.setattr(
        webagent.agent_dialogue, "call_agent_json",
        lambda chat_fn, planner: {"action": "answer", "reason": "enough evidence"},
    )
    action = webagent._research_action("what is the topic?", [], 0)
    assert action == {"action": "answer", "reason": "enough evidence"}


def test_falls_back_to_search_when_response_invalid_and_verification_required(monkeypatch):
    monkeypatch.setattr(webagent.agent_dialogue, "call_agent_json", lambda chat_fn, planner: None)
    action = webagent._research_action("who is the current president?", [], 0)
    assert action["action"] == "search"
    assert action["query"]  # _fallback_research_query produced something


def test_falls_back_to_answer_when_response_invalid_and_verification_not_required(monkeypatch):
    monkeypatch.setattr(webagent.agent_dialogue, "call_agent_json", lambda chat_fn, planner: None)
    action = webagent._research_action("tell me a fun fact about otters", [], 0)
    assert action == {"action": "answer", "reason": "The planner did not request a valid additional search."}


def test_planner_prompt_instructs_entity_resolution_for_corrections(monkeypatch):
    """The actual fix: the model must be told to resolve a correction to its
    full, correctly-spelled form before searching, not just search the
    user's raw correction text verbatim."""
    captured = {}

    def fake_call_agent_json(chat_fn, planner):
        captured["planner"] = planner
        return {"action": "answer", "reason": "n/a"}

    monkeypatch.setattr(webagent.agent_dialogue, "call_agent_json", fake_call_agent_json)

    webagent._research_action("no, it's called the reluctant messenger", [], 0)

    assert "resolve it" in captured["planner"]
    assert "correctly-spelled form" in captured["planner"]
    assert "no, it's called the reluctant messenger" in captured["planner"]
