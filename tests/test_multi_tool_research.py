"""Regression tests for _select_tool_actions/_execute_research_tool_action,
the multi-tool, model-driven research mechanism wired into
model_directed_web_research.

Replaces regex-based intent detection as the primary mechanism for
weather/stock/soccer-shaped questions - four separate real, reported regex
bugs were found and fixed in that area first (missing word orders, modifier
placement, tense) before this replaced regex as the primary path (the old
regex functions remain as a free, zero-latency fast path tried first - see
_try_live_lookup_bypasses). Explicitly supports selecting MULTIPLE tools per
turn (e.g. knowledge.search AND web.search AND a live.* lookup together)
since all of them are free and combining sources gives a fuller, better-
corroborated answer than stopping at the first hit.
"""
import webagent


def test_select_tool_actions_returns_empty_list_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(webagent, "ollama", None)
    assert webagent._select_tool_actions("what's the capital of France?") == []


def test_select_tool_actions_returns_empty_list_when_the_model_reply_is_not_json(fake_ollama_chat):
    fake_ollama_chat.reply = "Sure, happy to help!"
    assert webagent._select_tool_actions("what's the capital of France?") == []


def test_select_tool_actions_returns_empty_list_for_an_empty_selection(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": []}'
    assert webagent._select_tool_actions("what's 2+2?") == []


def test_select_tool_actions_selects_a_single_tool(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": [{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}]}'
    assert webagent._select_tool_actions("how did Man United do?") == [
        {"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}},
    ]


def test_select_tool_actions_selects_multiple_tools_at_once(fake_ollama_chat):
    """The actual, explicit ask: combine knowledge.search AND web.search AND
    a live API in the same turn rather than jumping at the first source."""
    fake_ollama_chat.reply = (
        '{"tools": ['
        '{"tool": "knowledge.search", "arguments": {"topic": "Manchester United"}}, '
        '{"tool": "web.search", "arguments": {"query": "Manchester United news"}}, '
        '{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}'
        ']}'
    )
    actions = webagent._select_tool_actions("what's going on with Man United?")
    assert actions == [
        {"tool": "knowledge.search", "arguments": {"topic": "Manchester United"}},
        {"tool": "web.search", "arguments": {"query": "Manchester United news"}},
        {"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}},
    ]


def test_select_tool_actions_rejects_off_topic_web_query(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": [{"tool": "web.search", "arguments": {"query": "Biosphere 3"}}]}'

    assert webagent._select_tool_actions("give me a list of 100 books to read before i die") == []


def test_select_tool_actions_rejects_a_tool_outside_the_catalog(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": [{"tool": "cron.remove", "arguments": {"index": 1}}]}'
    assert webagent._select_tool_actions("delete my alarm") == []


def test_select_tool_actions_rejects_a_selection_missing_a_required_argument(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": [{"tool": "live.soccer_result", "arguments": {}}]}'
    assert webagent._select_tool_actions("how did they do?") == []


def test_select_tool_actions_drops_an_argument_the_tool_does_not_accept(fake_ollama_chat):
    """Real, reported bug: the model supplied live.soccer_result with both
    "team" and a "location" left over from a live.weather call it made the
    turn before - tool_registry.execute raised a TypeError for the
    unexpected keyword (caught, so it failed safe, but wasted the turn and
    fell through to a worse fallback path that answered from a completely
    unrelated prior message). Must be dropped before ever attempting the
    call."""
    fake_ollama_chat.reply = (
        '{"tools": [{"tool": "live.soccer_result", "arguments": '
        '{"team": "Manchester United", "location": "United Kingdom"}}]}'
    )
    assert webagent._select_tool_actions("what's the score?") == [
        {"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}},
    ]


def test_select_tool_actions_drops_a_duplicate_tool_name(fake_ollama_chat):
    fake_ollama_chat.reply = (
        '{"tools": ['
        '{"tool": "live.stock_quote", "arguments": {"company_or_ticker": "MSFT"}}, '
        '{"tool": "live.stock_quote", "arguments": {"company_or_ticker": "MSFT"}}'
        ']}'
    )
    assert webagent._select_tool_actions("what is MSFT trading at?") == [
        {"tool": "live.stock_quote", "arguments": {"company_or_ticker": "MSFT"}},
    ]


def test_select_tool_actions_includes_recent_conversation_history(fake_ollama_chat):
    """The whole point: a follow-up naming no subject of its own must still
    reach the planner with enough context to resolve it."""
    webagent.context.assistant_convo = [
        webagent.sys_msgs.assistant_msg,
        {"role": "user", "content": "how did Man United do?"},
        {"role": "assistant", "content": "They lost to Hull City 2-0."},
    ]
    fake_ollama_chat.reply = '{"tools": []}'

    webagent._select_tool_actions("what about their next game?")

    sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
    assert "Man United" in sent_prompt
    assert "Hull City" in sent_prompt


def test_select_tool_actions_prompt_invites_combining_sources(fake_ollama_chat):
    fake_ollama_chat.reply = '{"tools": []}'
    webagent._select_tool_actions("anything")
    sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
    assert "MORE THAN ONE" in sent_prompt


class TestToolSelectionLogging:
    """The explicit ask: every tool-selection decision - including an empty
    one ("I don't know") - gets published as TOOL_SELECTION_MADE so it
    lands in the activity log (core/activity_log.py) with a timestamp and
    the model's stated reason, reviewable later instead of guessed at from
    a live trace."""

    def _capture(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            webagent.events, "publish",
            lambda name, **payload: captured.append((name, payload)),
        )
        return captured

    def test_publishes_on_a_successful_multi_tool_selection(self, fake_ollama_chat, monkeypatch):
        captured = self._capture(monkeypatch)
        fake_ollama_chat.reply = (
            '{"tools": [{"tool": "live.stock_quote", "arguments": {"company_or_ticker": "MSFT"}}], '
            '"reason": "user asked for a live stock price"}'
        )

        webagent._select_tool_actions("what is MSFT trading at?")

        assert len(captured) == 1
        name, payload = captured[0]
        assert name == webagent.TOOL_SELECTION_MADE
        assert payload["selected"] == ["live.stock_quote"]
        assert payload["reason"] == "user asked for a live stock price"
        assert payload["prompt"] == "what is MSFT trading at?"

    def test_publishes_with_an_empty_selection_and_a_reason(self, fake_ollama_chat, monkeypatch):
        captured = self._capture(monkeypatch)
        fake_ollama_chat.reply = '{"tools": [], "reason": "casual conversation, no tool needed"}'

        webagent._select_tool_actions("tell me a joke")

        assert captured == [(webagent.TOOL_SELECTION_MADE, {
            "prompt": "tell me a joke", "selected": [], "reason": "casual conversation, no tool needed",
        })]

    def test_singular_selector_also_publishes_on_selection(self, fake_ollama_chat, monkeypatch):
        captured = self._capture(monkeypatch)
        fake_ollama_chat.reply = '{"tool": "git.status", "reason": "user asked about repo state"}'

        webagent._select_tool_action("is the repo dirty right now?")

        assert len(captured) == 1
        name, payload = captured[0]
        assert name == webagent.TOOL_SELECTION_MADE
        assert payload["selected"] == ["git.status"]
        assert payload["reason"] == "user asked about repo state"

    def test_singular_selector_publishes_when_the_model_picks_nothing(self, fake_ollama_chat, monkeypatch):
        captured = self._capture(monkeypatch)
        fake_ollama_chat.reply = '{"tool": null, "reason": "general knowledge question"}'

        webagent._select_tool_action("what's the capital of France?")

        assert captured == [(webagent.TOOL_SELECTION_MADE, {
            "prompt": "what's the capital of France?", "selected": [], "reason": "general knowledge question",
        })]


def test_select_tool_actions_prompt_says_not_to_guess():
    """The explicit ask: if the model can't tell which subject the user
    means, it should say it doesn't know rather than guess an argument."""
    import inspect
    source = inspect.getsource(webagent._select_tool_actions)
    assert "do not guess" in source.lower()


class TestKnowledgeSearchEvidence:
    def test_normalizes_results_into_evidence_shape(self):
        results = [("notes.txt", "Some saved research content."), ("other.txt", "More content.")]
        evidence = webagent._knowledge_search_evidence("my query", results)
        assert len(evidence) == 2
        assert evidence[0]["title"] == "Knowledge base - notes.txt"
        assert evidence[0]["content"] == "Some saved research content."
        assert evidence[0]["url"] == "knowledge_base://notes.txt"
        assert evidence[0]["truthfulness_confidence"] > 0

    def test_empty_results_yield_no_evidence(self):
        assert webagent._knowledge_search_evidence("my query", []) == []


class TestExecuteResearchToolAction:
    def test_live_soccer_result_becomes_one_evidence_item(self, monkeypatch):
        fake_evidence = {"title": "Live soccer results - X", "content": "...", "url": "https://espn.com"}
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: fake_evidence)
        result = webagent._execute_research_tool_action(
            {"tool": "live.soccer_result", "arguments": {"team": "Man United"}}, "how did they do?",
        )
        assert result == [fake_evidence]

    def test_a_failed_live_lookup_yields_no_evidence(self, monkeypatch):
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: None)
        result = webagent._execute_research_tool_action(
            {"tool": "live.soccer_result", "arguments": {"team": "Nonexistent FC"}}, "how did they do?",
        )
        assert result == []

    def test_web_search_results_get_saved_as_evidence(self, isolated_data_dir, monkeypatch):
        fake_result = {"title": "A page", "url": "https://example.com/a", "content": "Real background content here."}
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: [fake_result])
        result = webagent._execute_research_tool_action(
            {"tool": "web.search", "arguments": {"query": "test query"}}, "what's the topic?",
        )
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/a"

    def test_knowledge_search_results_get_normalized(self, monkeypatch):
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: [("notes.txt", "content")])
        result = webagent._execute_research_tool_action(
            {"tool": "knowledge.search", "arguments": {"topic": "x"}}, "what do we know about x?",
        )
        assert len(result) == 1
        assert result[0]["title"] == "Knowledge base - notes.txt"

    def test_a_tool_execution_error_is_swallowed(self, monkeypatch):
        def _raise(name, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(webagent.tool_registry, "execute", _raise)
        result = webagent._execute_research_tool_action(
            {"tool": "live.weather", "arguments": {"location": "Boston"}}, "what's the weather?",
        )
        assert result == []

    def test_publishes_tool_execution_completed_on_success(self, monkeypatch):
        captured = []
        monkeypatch.setattr(webagent.events, "publish", lambda name, **payload: captured.append((name, payload)))
        fake_evidence = {"title": "X", "content": "...", "url": "https://espn.com"}
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: fake_evidence)

        webagent._execute_research_tool_action(
            {"tool": "live.soccer_result", "arguments": {"team": "Man United"}}, "how did they do?",
        )

        assert captured == [(webagent.TOOL_EXECUTION_COMPLETED, {
            "tool": "live.soccer_result", "arguments": {"team": "Man United"},
            "success": True, "error": None, "evidence_count": 1,
        })]

    def test_publishes_tool_execution_completed_with_zero_evidence_when_nothing_found(self, monkeypatch):
        captured = []
        monkeypatch.setattr(webagent.events, "publish", lambda name, **payload: captured.append((name, payload)))
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: None)

        webagent._execute_research_tool_action(
            {"tool": "live.soccer_result", "arguments": {"team": "Nonexistent FC"}}, "how did they do?",
        )

        assert captured == [(webagent.TOOL_EXECUTION_COMPLETED, {
            "tool": "live.soccer_result", "arguments": {"team": "Nonexistent FC"},
            "success": False, "error": None, "evidence_count": 0,
        })]

    def test_publishes_tool_execution_completed_on_error(self, monkeypatch):
        captured = []
        monkeypatch.setattr(webagent.events, "publish", lambda name, **payload: captured.append((name, payload)))

        def _raise(name, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(webagent.tool_registry, "execute", _raise)

        webagent._execute_research_tool_action(
            {"tool": "live.weather", "arguments": {"location": "Boston"}}, "what's the weather?",
        )

        assert captured == [(webagent.TOOL_EXECUTION_COMPLETED, {
            "tool": "live.weather", "arguments": {"location": "Boston"},
            "success": False, "error": "boom", "evidence_count": 0,
        })]


def test_app_started_event_is_published_with_model_and_registry_info():
    """Real ask: a timestamped row per process launch, so "was the app even
    running, and since when" is answerable from the activity log."""
    captured = []
    handler = lambda **payload: captured.append(payload)  # noqa: E731
    webagent.events.subscribe(webagent.APP_STARTED, handler)
    try:
        webagent.events.publish(
            webagent.APP_STARTED, main_model=webagent.MODELS.get("main"),
            coding_model=webagent.MODELS.get("coding"), search_model=webagent.MODELS.get("search"),
            tool_count=len(webagent.tool_registry.list()), skill_count=len(webagent.skill_registry.list()),
        )
        assert len(captured) == 1
        assert captured[0]["main_model"] == webagent.MODELS["main"]
        assert captured[0]["tool_count"] > 0
    finally:
        webagent.events.unsubscribe(webagent.APP_STARTED, handler)


def test_model_directed_web_research_combines_evidence_from_multiple_selected_tools(isolated_data_dir, monkeypatch):
    """The explicit ask, end to end: multiple free sources combine into one
    answer instead of stopping at the first hit."""
    webagent.context.deep_think_mode = False
    # Isolate this from the free regex fast-path (_try_live_lookup_bypasses)
    # so the test exercises _select_tool_actions's combination behavior
    # regardless of whether the prompt also happens to match a regex shape.
    monkeypatch.setattr(webagent, "_try_live_lookup_bypasses", lambda query_text: None)
    monkeypatch.setattr(
        webagent, "_select_tool_actions",
        lambda prompt: [
            {"tool": "knowledge.search", "arguments": {"topic": "Manchester United"}},
            {"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}},
        ],
    )
    monkeypatch.setattr(webagent.tool_registry, "get", webagent.tool_registry.get)

    def fake_execute(name, **kwargs):
        if name == "knowledge.search":
            return [("notes.txt", "Prior research about Manchester United.")]
        if name == "live.soccer_result":
            return {
                "title": "Live soccer results - Manchester United", "content": "Lost 2-0 to Hull City.",
                "url": "https://espn.com", "truthfulness_confidence": 90, "recency_confidence": 100,
                "corroborating_domains": [],
            }
        raise AssertionError(f"unexpected tool: {name}")

    monkeypatch.setattr(webagent.tool_registry, "execute", fake_execute)
    monkeypatch.setattr(webagent, "_research_action", lambda prompt, evidence, searches_used: {"action": "answer"})

    evidence = webagent.model_directed_web_research("how did Man United do?")

    sources = {item.get("search_provider") for item in evidence}
    assert "knowledge-base" in sources
    assert any("Hull City" in item.get("content", "") for item in evidence)


class TestLiveEvidenceStaysAuthoritative:
    """Regression tests for a real, live-reported bug: a live.soccer_result
    hit was correctly found ("Hull City 2-0 Manchester United"), but the
    iterative research loop kept running anyway - _research_action's "you
    MUST search" instruction for sports results doesn't know a live API
    already answered the question - piling 5 more generic web searches on
    top. apply_corroboration then recomputed the live item's confidence
    using corroboration math meant for scraped web pages (0.4*90 + 0.6*40 =
    ~60, since it shares no "fact tokens" with unrelated web snippets),
    letting noisy, unrelated results outrank the correct answer. The final
    reply confidently reported a fabricated 0-0 score - two bugs, two fixes:
    _select_tool_actions's evidence now returns immediately instead of
    falling into the loop, and apply_corroboration never touches a live
    item's confidence at all.
    """

    def test_apply_corroboration_does_not_touch_a_live_items_confidence(self):
        live_item = {
            "content": "Live quote for X.", "url": "https://finance.yahoo.com/quote/X",
            "search_provider": "yahoo-finance", "truthfulness_confidence": 90, "recency_confidence": 100,
        }
        web_item = {
            "content": "Some unrelated generic web page content about a totally different topic.",
            "url": "https://example.com/a", "search_provider": "searxng", "truthfulness_confidence": 40,
        }
        webagent.apply_corroboration([live_item, web_item])
        assert live_item["truthfulness_confidence"] == 90

    def test_apply_corroboration_still_scores_non_authoritative_evidence_normally(self):
        """The protection is scoped to live providers only - ordinary web
        results must still get real corroboration scoring."""
        web_item = {
            "content": "Some page with no shared facts with anything else.",
            "url": "https://example.com/a", "search_provider": "searxng", "truthfulness_confidence": 90,
        }
        webagent.apply_corroboration([web_item])
        assert web_item["truthfulness_confidence"] != 90  # recomputed, not left untouched

    def test_model_directed_web_research_returns_immediately_when_tools_are_selected(self, isolated_data_dir, monkeypatch):
        """The core fix: the iterative refinement loop (and its "you MUST
        search" forcing) must never run once _select_tool_actions has
        already produced evidence - that evidence is the model's
        deliberate, considered choice for this turn, not a tentative first
        guess to second-guess with more searching."""
        webagent.context.deep_think_mode = False
        monkeypatch.setattr(webagent, "_try_live_lookup_bypasses", lambda query_text: None)
        monkeypatch.setattr(
            webagent, "_select_tool_actions",
            lambda prompt: [{"tool": "live.soccer_result", "arguments": {"team": "Manchester United"}}],
        )
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: {
            "title": "Live soccer results - Manchester United", "content": "Hull City 2-0 Manchester United.",
            "url": "https://www.espn.com/soccer/team/_/id/360", "search_provider": "espn",
            "truthfulness_confidence": 90, "recency_confidence": 100, "corroborating_domains": [],
        })

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("the iterative loop must not run when tool-selected evidence already exists")

        monkeypatch.setattr(webagent, "_research_action", _fail_if_called)
        monkeypatch.setattr(webagent.tool_registry.get("web.search"), "_search_fn", _fail_if_called)

        evidence = webagent.model_directed_web_research("what was the score for the last Manchester United game?")

        assert len(evidence) == 1
        assert evidence[0]["truthfulness_confidence"] == 90
        assert "Hull City 2-0 Manchester United" in evidence[0]["content"]
