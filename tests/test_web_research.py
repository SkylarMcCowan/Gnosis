"""Regression tests for /websearch and /deepthink's research pipeline
(model_directed_web_research, webagent.py:1353-1408) and /askwiki (ask_wiki,
webagent.py:3130-3164). All network calls (search_web, requests.get) and the
planner's LLM call (agent_dialogue.call_agent_json) are mocked - this suite
must never make a real HTTP request.
"""
import webagent


def test_model_directed_web_research_runs_one_search_then_answers(isolated_data_dir, monkeypatch):
    fake_result = {
        "title": "Example result",
        "url": "https://example.com/a",
        "content": "Some background content about the topic, long enough to score decently.",
        "search_provider": "test",
    }
    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [fake_result])

    decisions = iter([
        {"action": "search", "query": "test query"},
        {"action": "answer"},
    ])
    monkeypatch.setattr(webagent.agent_dialogue, "call_agent_json", lambda chat_fn, planner: next(decisions))

    evidence = webagent.model_directed_web_research("what is the topic?")

    assert len(evidence) == 1
    assert evidence[0]["url"] == "https://example.com/a"
    saved_dir = isolated_data_dir / "knowledge_base" / "web_evidence"
    assert len(list(saved_dir.glob("*.json"))) == 1


def test_model_directed_web_research_stops_on_duplicate_query(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", lambda query: [])
    monkeypatch.setattr(
        webagent.agent_dialogue, "call_agent_json",
        lambda chat_fn, planner: {"action": "search", "query": "same query"},
    )

    # First loop: seeds "same query"; the immediate re-ask returns the same
    # query again, which the seen_queries guard must stop on instead of
    # looping forever.
    evidence = webagent.model_directed_web_research("tell me about same query")

    assert evidence == []


def test_model_directed_web_research_stops_on_near_duplicate_queries(isolated_data_dir, monkeypatch):
    """A planner stuck rephrasing the same unresolved reference ("the
    reluctant messenger book" -> "reluctant messenger book title" -> ...)
    must not be allowed to search indefinitely just because no two queries
    are an exact match - see TODO.md Phase 6's repeated-query cutoff item."""
    search_calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("web.search"), "_search_fn",
        lambda query: search_calls.append(query) or [],
    )
    rephrasings = iter([
        "the reluctant messenger book",
        "reluctant messenger book title",
        "book titled the reluctant messenger",
        "the reluctant messenger book title",
    ])
    monkeypatch.setattr(
        webagent.agent_dialogue, "call_agent_json",
        lambda chat_fn, planner: {"action": "search", "query": next(rephrasings, "the reluctant messenger book title")},
    )

    evidence = webagent.model_directed_web_research("tell me about the reluctant messenger")

    assert evidence == []
    # One near-duplicate refinement is allowed; a second consecutive one cuts it off.
    assert len(search_calls) == 2
    assert search_calls == ["the reluctant messenger book", "reluctant messenger book title"]


def test_query_words_ignores_short_words():
    assert webagent._query_words("the reluctant messenger book") == {"reluctant", "messenger", "book"}


def test_is_near_duplicate_query_true_for_a_close_rephrasing():
    assert webagent._is_near_duplicate_query(
        "reluctant messenger book title", ["the reluctant messenger book"]
    ) is True


def test_is_near_duplicate_query_false_for_a_genuinely_different_angle():
    assert webagent._is_near_duplicate_query(
        "reluctant messenger book recent developments", ["the reluctant messenger book"]
    ) is False


def test_is_near_duplicate_query_false_with_no_significant_word_overlap():
    assert webagent._is_near_duplicate_query("stoicism daily practice", ["reluctant messenger book"]) is False


def test_forced_continuation_queries_are_exempt_from_the_near_duplicate_guard(isolated_data_dir, monkeypatch):
    """Deep Think's forced continuations deliberately reuse the same base
    query with a rotating angle suffix (_deep_think_forced_query) - the
    near-duplicate guard must not mistake that deliberate repetition for a
    planner stuck rephrasing an unresolved query."""
    webagent.context.deep_think_mode = True
    monkeypatch.setattr(webagent, "_deep_think_research_plan", lambda prompt: None)
    search_calls = []
    fake_result = {"title": "Example", "url": "https://example.com/a", "content": "Some real background content."}
    monkeypatch.setattr(
        webagent.tool_registry.get("web.search"), "_search_fn",
        lambda query: search_calls.append(query) or [fake_result],
    )
    # Every planner call "answers" - the DEEP_THINK_MIN_SEARCHES floor is what
    # forces the continuations, not the planner choosing to keep searching.
    monkeypatch.setattr(
        webagent.agent_dialogue, "call_agent_json",
        lambda chat_fn, planner: {"action": "answer", "reason": "n/a"},
    )

    webagent.model_directed_web_research("tell me about the reluctant messenger")

    # 1 seed search (the fallback plan) + one forced continuation per search
    # number below the floor (1, 2, 3) = DEEP_THINK_MIN_SEARCHES total.
    assert len(search_calls) == webagent.DEEP_THINK_MIN_SEARCHES
    webagent.context.deep_think_mode = False


def test_ask_wiki_falls_back_to_web_search_on_missing_page(isolated_data_dir, fake_ollama_chat, monkeypatch):
    class FakeResponse:
        status_code = 404
        text = ""

    monkeypatch.setattr(webagent.requests, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(webagent, "iterative_web_search", lambda query: "fallback web search summary")

    webagent.ask_wiki("Zzznonexistentpage")

    assert webagent.context.assistant_convo[-1]["role"] == "assistant"
    assert webagent.context.assistant_convo[-1]["content"] == fake_ollama_chat.reply
    saved = list((isolated_data_dir / "knowledge_base").glob("wiki_*.txt"))
    assert len(saved) == 1
    assert "fallback web search summary" in saved[0].read_text()
