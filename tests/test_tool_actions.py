"""Regression tests for the model-driven tool-selection step
(_select_tool_action/_execute_tool_action, wired into chat_response and
_handle_unmatched_prompt) - lets the model decide, once per turn, whether
one of Gnosis's own SAFE read-only capabilities (repo audit, git status/
diff, the crontab listing, the knowledge base, sandboxed file reads) would
help answer the user's message.

Deliberately NOT built on Ollama's native tools= mechanism: confirmed live
before writing this that this app's default model (yi:6b) doesn't support
it at all (Ollama raises "does not support tools"), and qwen2.5-coder:7b
accepts the schema but writes the tool call out as plain JSON text instead
of a real tool_calls response. Uses the same model-agnostic JSON-decision
protocol _research_action already uses for web search
(agent_dialogue.call_agent_json), which works uniformly across every local
model this app runs.
"""
import webagent
from tools.base import Permission, Tool


class _FakeTool(Tool):
    def __init__(self, name, description="", parameters=None, permission=Permission.SAFE, result="ok", raises=None):
        self.name = name
        self.description = description
        self.parameters = parameters or {}
        self.permission = permission
        self._result = result
        self._raises = raises

    def execute(self, **kwargs):
        if self._raises:
            raise self._raises
        return self._result


class TestAvailableToolActions:
    def test_includes_only_safe_tools(self, monkeypatch):
        safe_tool = _FakeTool("test.safe", permission=Permission.SAFE)
        restricted_tool = _FakeTool("test.restricted", permission=Permission.RESTRICTED)
        approval_tool = _FakeTool("test.approval", permission=Permission.REQUIRES_APPROVAL)
        monkeypatch.setattr(webagent.tool_registry, "list", lambda: [safe_tool, restricted_tool, approval_tool])

        names = {t.name for t in webagent._available_tool_actions()}
        assert names == {"test.safe"}

    def test_excludes_research_tools_even_though_they_are_safe(self, monkeypatch):
        """These go through _select_tool_actions instead (wired into
        model_directed_web_research), which combines multiple free sources
        and feeds the result through evidence scoring/fact-checking -
        offering them here too would be a second, uncoordinated path to the
        same capabilities with none of that pipeline behind it."""
        search = _FakeTool("web.search", permission=Permission.SAFE)
        fetch = _FakeTool("web.fetch", permission=Permission.SAFE)
        knowledge = _FakeTool("knowledge.search", permission=Permission.SAFE)
        weather = _FakeTool("live.weather", permission=Permission.SAFE)
        other = _FakeTool("git.status", permission=Permission.SAFE)
        monkeypatch.setattr(webagent.tool_registry, "list", lambda: [search, fetch, knowledge, weather, other])

        names = {t.name for t in webagent._available_tool_actions()}
        assert names == {"git.status"}

    def test_reflects_the_real_registered_tools(self):
        """Not a mock - proves the real app-wired registry actually yields
        the expected SAFE, non-research catalog right now."""
        names = {t.name for t in webagent._available_tool_actions()}
        assert names == {
            "cron.list", "git.status", "git.diff", "repo.audit", "repo.audit_advanced", "fs.read",
            "subscriptions.list",
        }


class TestSelectToolAction:
    def test_returns_no_tool_when_ollama_unavailable(self, monkeypatch):
        monkeypatch.setattr(webagent, "ollama", None)
        assert webagent._select_tool_action("what's in the knowledge base about X?") == {"tool": None}

    def test_returns_no_tool_when_the_catalog_is_empty(self, monkeypatch):
        monkeypatch.setattr(webagent, "_available_tool_actions", lambda: [])
        assert webagent._select_tool_action("anything") == {"tool": None}

    def test_returns_no_tool_when_the_model_reply_is_not_json(self, fake_ollama_chat):
        fake_ollama_chat.reply = "Sure, I can help with that!"
        assert webagent._select_tool_action("what's the weather like?") == {"tool": None}

    def test_returns_no_tool_when_the_model_says_null(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": null}'
        assert webagent._select_tool_action("hello there") == {"tool": None}

    def test_returns_no_tool_when_the_model_names_a_tool_outside_the_catalog(self, fake_ollama_chat):
        """A model naming a real but excluded/unregistered tool (or a
        hallucinated one) must not be trusted just because the JSON parsed -
        the name has to match an offered SAFE tool."""
        fake_ollama_chat.reply = '{"tool": "web.search", "arguments": {"query": "x"}}'
        assert webagent._select_tool_action("search the web for x") == {"tool": None}

    def test_selects_a_valid_tool_with_arguments(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": "fs.read", "arguments": {"workspace_id": "abc", "path": "notes.txt"}}'
        assert webagent._select_tool_action("read notes.txt from the sandbox") == {
            "tool": "fs.read", "arguments": {"workspace_id": "abc", "path": "notes.txt"},
        }

    def test_rejects_a_tool_missing_a_required_argument(self, fake_ollama_chat):
        """Real, reported bug (originally seen with knowledge.search, since
        moved to _select_tool_actions - the underlying validation this
        guards is the same regardless of which tool it's applied to): the
        model picked a tool but left a required argument out of
        "arguments" - the call reached tool_registry.execute and raised a
        TypeError there (caught, so it failed safe, but wasted the turn).
        Must be rejected before ever attempting the call."""
        fake_ollama_chat.reply = '{"tool": "fs.read", "arguments": {"workspace_id": "abc"}}'
        assert webagent._select_tool_action("read a file from the sandbox") == {"tool": None}

    def test_rejects_a_tool_with_no_arguments_key_at_all_when_one_is_required(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": "fs.read"}'
        assert webagent._select_tool_action("read a file from the sandbox") == {"tool": None}

    def test_drops_an_argument_the_tool_does_not_accept(self, fake_ollama_chat):
        """Real, reported bug: the model supplied an extra argument the tool
        doesn't declare at all (e.g. a "location" left over from a
        different tool it used the turn before) - tool_registry.execute
        raised a TypeError for the unexpected keyword (caught, so it
        failed safe, but wasted the turn and fell through to a worse
        fallback path). Must be dropped before ever attempting the call,
        not just checked for missing required ones."""
        fake_ollama_chat.reply = (
            '{"tool": "fs.read", "arguments": {"workspace_id": "abc", "path": "notes.txt", "location": "London"}}'
        )
        assert webagent._select_tool_action("read notes.txt") == {
            "tool": "fs.read", "arguments": {"workspace_id": "abc", "path": "notes.txt"},
        }

    def test_selects_a_valid_tool_with_no_arguments(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": "git.status"}'
        assert webagent._select_tool_action("is the repo dirty right now?") == {"tool": "git.status", "arguments": {}}

    def test_defaults_arguments_to_empty_dict_when_not_a_dict(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": "repo.audit", "arguments": "none needed"}'
        assert webagent._select_tool_action("audit the repo") == {"tool": "repo.audit", "arguments": {}}

    def test_prompt_lists_the_available_capabilities(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": null}'
        webagent._select_tool_action("what tools do you have?")
        sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
        assert "git.status" in sent_prompt

    def test_skips_the_model_call_entirely_for_a_weather_shaped_query(self, fake_ollama_chat):
        """A real, live-observed collision from before research tools moved
        to _select_tool_actions: yi:6b sometimes routed a plain weather
        question to a local capability despite an explicit in-prompt
        instruction not to. Fixed with a deterministic skip instead - no
        model call happens at all for a query the live-lookup bypasses
        already own."""
        assert webagent._select_tool_action("what's the weather today?") == {"tool": None}
        assert fake_ollama_chat.calls == []

    def test_skips_the_model_call_entirely_for_a_stock_shaped_query(self, fake_ollama_chat):
        assert webagent._select_tool_action("what is the price of TESLA?") == {"tool": None}
        assert fake_ollama_chat.calls == []

    def test_skips_the_model_call_entirely_for_a_soccer_shaped_query(self, fake_ollama_chat):
        assert webagent._select_tool_action("how did Man United do?") == {"tool": None}
        assert fake_ollama_chat.calls == []

    def test_does_not_skip_a_legitimate_local_question_containing_a_generic_time_word(self, fake_ollama_chat):
        """Real bug caught by testing this live: requires_current_web_
        verification's broad word list ("now", "today", "current", ...)
        would wrongly suppress a legitimate git.status question just for
        containing "now" - the skip must be scoped to the three specific
        live-lookup detectors, not that broader check."""
        fake_ollama_chat.reply = '{"tool": "git.status"}'
        assert webagent._select_tool_action("is the repo dirty right now?") == {"tool": "git.status", "arguments": {}}

    def test_selects_subscriptions_list_for_a_subscriptions_question(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": "subscriptions.list", "reason": "user asked what they follow"}'
        assert webagent._select_tool_action("give me an update on my subscriptions?") == {
            "tool": "subscriptions.list", "arguments": {},
        }

    def test_prompt_mentions_subscriptions_as_an_allowed_topic(self, fake_ollama_chat):
        fake_ollama_chat.reply = '{"tool": null}'
        webagent._select_tool_action("what am I subscribed to?")
        sent_prompt = fake_ollama_chat.calls[0]["messages"][0]["content"]
        assert "subscriptions" in sent_prompt.lower()


class TestSummarizeToolResult:
    def test_repo_audit_returns_the_string_as_is(self):
        assert webagent._summarize_tool_result("repo.audit", "Repository root: /x\nTotal files: 3") == "Repository root: /x\nTotal files: 3"

    def test_knowledge_search_formats_matching_files(self):
        result = [("notes.txt", "Some content about overview effect and awe."), ("other.txt", "Different topic.")]
        summary = webagent._summarize_tool_result("knowledge.search", result)
        assert "- notes.txt: Some content about overview effect" in summary
        assert "- other.txt: Different topic." in summary

    def test_subscriptions_list_formats_each_record_with_its_type(self):
        result = [{"type": "team", "name": "Manchester United"}, {"type": "weather", "name": "Tucson, Arizona, United States"}]
        summary = webagent._summarize_tool_result("subscriptions.list", result)
        assert "- [Team] Manchester United" in summary
        assert "- [Weather] Tucson, Arizona, United States" in summary

    def test_subscriptions_list_handles_no_subscriptions(self):
        assert webagent._summarize_tool_result("subscriptions.list", []) == "No subscriptions yet."

    def test_knowledge_search_handles_no_matches(self):
        assert webagent._summarize_tool_result("knowledge.search", []) == "No matching entries found in the knowledge base."

    def test_cron_list_formats_entries_with_their_real_schedule(self):
        """Real, live-observed bug: without the actual schedule in the
        summary, the model invented plausible-sounding but fabricated
        times ("at 08:00 AM") for tasks it had no real time for at all."""
        entries = [
            {"description": "Nightly overnight cycle", "command_line": "0 2 * * * cd /x && python3 webagent.py"},
            {"description": None, "command_line": "19 17 19 8 * cd /x && python3 webagent.py"},
        ]
        summary = webagent._summarize_tool_result("cron.list", (entries, None))
        assert "#1 Nightly overnight cycle (schedule: 0 2 * * *)" in summary
        assert "#2 (no description) (schedule: 19 17 19 8 *)" in summary

    def test_cron_list_surfaces_the_error_message(self):
        assert webagent._summarize_tool_result("cron.list", ([], "crontab unavailable")) == "crontab unavailable"

    def test_cron_list_handles_no_entries(self):
        assert webagent._summarize_tool_result("cron.list", ([], None)) == "No scheduled tasks."

    def test_git_status_returns_stdout_on_success(self):
        assert webagent._summarize_tool_result("git.status", (0, " M webagent.py\n", "")) == "M webagent.py"

    def test_git_status_reports_clean_tree(self):
        assert webagent._summarize_tool_result("git.status", (0, "", "")) == "(clean - no output)"

    def test_git_diff_surfaces_stderr_on_failure(self):
        assert webagent._summarize_tool_result("git.diff", (128, "", "fatal: not a git repository")) == "git command failed: fatal: not a git repository"

    def test_unknown_tool_falls_back_to_str(self):
        assert webagent._summarize_tool_result("fs.read", {"content": "hello"}) == "{'content': 'hello'}"


class TestExecuteToolAction:
    def test_returns_none_when_no_tool_was_selected(self):
        assert webagent._execute_tool_action({"tool": None}) is None

    def test_executes_the_tool_and_formats_the_result(self, monkeypatch):
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: "Repository root: /x")
        result = webagent._execute_tool_action({"tool": "repo.audit", "arguments": {}})
        assert result == "[repo.audit] Repository root: /x"

    def test_passes_arguments_through_to_the_tool(self, monkeypatch):
        calls = []
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: calls.append((name, kwargs)) or [])
        webagent._execute_tool_action({"tool": "knowledge.search", "arguments": {"topic": "awe"}})
        assert calls == [("knowledge.search", {"topic": "awe"})]

    def test_swallows_a_tool_execution_error_and_returns_none(self, monkeypatch):
        def _raise(name, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(webagent.tool_registry, "execute", _raise)
        assert webagent._execute_tool_action({"tool": "knowledge.search", "arguments": {"topic": "x"}}) is None

    def test_publishes_tool_execution_completed_on_success(self, monkeypatch):
        captured = []
        monkeypatch.setattr(webagent.events, "publish", lambda name, **payload: captured.append((name, payload)))
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: "Repository root: /x")

        webagent._execute_tool_action({"tool": "repo.audit", "arguments": {}})

        assert captured == [(webagent.TOOL_EXECUTION_COMPLETED, {
            "tool": "repo.audit", "arguments": {}, "success": True, "error": None,
        })]

    def test_publishes_tool_execution_completed_on_failure(self, monkeypatch):
        captured = []
        monkeypatch.setattr(webagent.events, "publish", lambda name, **payload: captured.append((name, payload)))

        def _raise(name, **kwargs):
            raise RuntimeError("boom")
        monkeypatch.setattr(webagent.tool_registry, "execute", _raise)

        webagent._execute_tool_action({"tool": "knowledge.search", "arguments": {"topic": "x"}})

        assert captured == [(webagent.TOOL_EXECUTION_COMPLETED, {
            "tool": "knowledge.search", "arguments": {"topic": "x"}, "success": False, "error": "boom",
        })]

    def test_cron_list_asks_the_user_to_confirm_instead_of_trusting_a_model_translation(self, monkeypatch):
        """Real bug: yi:6b's plain-English narration of raw cron syntax was
        unreliable (a daily "0 2 * * *" task got described as running on
        "the 1st, 3rd, 5th of each month"). Fixed by asking the user to
        confirm the real schedule instead of trusting a translation. The
        real schedule data must still reach the answering model alongside
        the confirmation - a second real bug, caught live: returning only
        "the user said it's correct" left it with no actual task data and
        it hallucinated a completely fictional task list instead."""
        entries = [{"description": "Nightly cycle", "command_line": "0 2 * * * cd /x && python3 webagent.py"}]
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: (entries, None))
        asked = {}

        def fake_ask(questions):
            asked["question"] = questions[0]["question"]
            return {questions[0]["question"]: "Yes, that's correct."}

        monkeypatch.setattr(webagent.agent_dialogue, "ask_user_question", fake_ask)

        result = webagent._execute_tool_action({"tool": "cron.list", "arguments": {}})

        assert "0 2 * * *" in asked["question"]
        assert "Nightly cycle" in asked["question"]
        assert "#1 Nightly cycle (schedule: 0 2 * * *)" in result  # the real data, still present
        assert "The user reviewed this schedule and said: Yes, that's correct." in result

    def test_cron_list_lets_the_user_supply_a_correction(self, monkeypatch):
        entries = [{"description": "Nightly cycle", "command_line": "0 2 * * * cd /x && python3 webagent.py"}]
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: (entries, None))
        monkeypatch.setattr(
            webagent.agent_dialogue, "ask_user_question",
            lambda questions: {questions[0]["question"]: "Actually the nightly cycle should run at 4 AM, not 2 AM."},
        )

        result = webagent._execute_tool_action({"tool": "cron.list", "arguments": {}})

        assert "#1 Nightly cycle (schedule: 0 2 * * *)" in result  # the real data, still present
        assert "4 AM, not 2 AM" in result

    def test_cron_list_falls_back_to_the_plain_summary_when_the_user_gives_no_answer(self, monkeypatch):
        entries = [{"description": "Nightly cycle", "command_line": "0 2 * * * cd /x && python3 webagent.py"}]
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: (entries, None))
        monkeypatch.setattr(webagent.agent_dialogue, "ask_user_question", lambda questions: {questions[0]["question"]: "   "})

        result = webagent._execute_tool_action({"tool": "cron.list", "arguments": {}})

        assert result == "[cron.list] #1 Nightly cycle (schedule: 0 2 * * *)"

    def test_cron_list_does_not_ask_when_there_are_no_entries(self, monkeypatch):
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: ([], None))
        asked = []
        monkeypatch.setattr(webagent.agent_dialogue, "ask_user_question", lambda questions: asked.append(questions) or {})

        result = webagent._execute_tool_action({"tool": "cron.list", "arguments": {}})

        assert asked == []
        assert result == "[cron.list] No scheduled tasks."

    def test_cron_list_does_not_ask_when_crontab_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(webagent.tool_registry, "execute", lambda name, **kwargs: ([], "crontab unavailable"))
        asked = []
        monkeypatch.setattr(webagent.agent_dialogue, "ask_user_question", lambda questions: asked.append(questions) or {})

        result = webagent._execute_tool_action({"tool": "cron.list", "arguments": {}})

        assert asked == []
        assert result == "[cron.list] crontab unavailable"


class TestChatResponseIntegration:
    def test_injects_the_tool_result_as_additional_context_without_leaking_into_the_users_answer(self, isolated_data_dir, fake_ollama_chat, monkeypatch):
        webagent.context.web_search_mode = False
        monkeypatch.setattr(webagent, "_select_tool_action", lambda prompt: {"tool": "repo.audit", "arguments": {}})
        monkeypatch.setattr(webagent, "_execute_tool_action", lambda action: "[repo.audit] Repository root: /x, 42 files")
        fake_ollama_chat.reply = "A drafted answer."

        result = webagent.chat_response("what does this repo look like?")

        assert result == "A drafted answer."  # the tool summary must not leak into the user-visible reply
        system_contents = [m["content"] for m in webagent.context.assistant_convo if m["role"] == "system"]
        assert any("Repository root: /x, 42 files" in c for c in system_contents)

    def test_no_extra_context_added_when_no_tool_is_selected(self, isolated_data_dir, fake_ollama_chat, monkeypatch):
        webagent.context.web_search_mode = False
        monkeypatch.setattr(webagent, "_select_tool_action", lambda prompt: {"tool": None})
        fake_ollama_chat.reply = "A drafted answer."

        webagent.chat_response("hello")

        system_contents = [m["content"] for m in webagent.context.assistant_convo if m["role"] == "system"]
        assert not any("Gnosis capability" in c for c in system_contents)

    def test_runs_even_when_research_mode_is_on(self, isolated_data_dir, fake_ollama_chat, monkeypatch):
        """The tool-selection step is independent of web_search_mode - a
        repo-audit-shaped question shouldn't require toggling web search on."""
        webagent.context.web_search_mode = True
        monkeypatch.setattr(webagent, "model_directed_web_research", lambda prompt: [])
        calls = []
        monkeypatch.setattr(webagent, "_select_tool_action", lambda prompt: calls.append(prompt) or {"tool": None})
        fake_ollama_chat.reply = "A drafted answer."

        webagent.chat_response("what's the git status?")

        assert calls == ["what's the git status?"]
