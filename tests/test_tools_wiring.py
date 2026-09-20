"""Confirms webagent.py actually registers its real capabilities with the
shared tools.registry.registry - not just that the Tool classes work in
isolation (tests/test_tools_web_search.py already covers that).
"""
import os
import subprocess

from tools.registry import registry as tool_registry
import penpot
import webagent

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Gnosis Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Gnosis Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _run_git(repo_dir, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo_dir, capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def test_web_search_tool_is_registered_and_reaches_the_real_search_pipeline(monkeypatch, isolated_data_dir):
    """The tool was constructed with webagent.search_web itself at
    registration time. Mocking search_web's own dependency (search_searx)
    and invoking the tool through the registry - rather than calling
    search_web directly - proves the tool is wired to the real pipeline,
    not a stand-in. isolated_data_dir is needed now too: search_web
    publishes SEARCH_COMPLETED (Phase 12), which the activity-log
    subscriber persists to disk."""
    tool = tool_registry.get("web.search")
    assert tool is not None

    monkeypatch.setattr(
        webagent, "search_searx",
        lambda query: [{"title": "Example", "url": "https://example.com", "content": "..."}],
    )

    result = tool_registry.execute("web.search", query="astronomy")

    assert result == [{"title": "Example", "url": "https://example.com", "content": "...", "search_provider": "searxng"}]


def test_conversation_inspect_tool_is_registered_and_bounded(monkeypatch):
    import webagent

    monkeypatch.setattr(webagent.context, "assistant_convo", [
        webagent.sys_msgs.assistant_msg,
        {"role": "user", "content": "give me a list of 100 books to read before i die"},
        {"role": "assistant", "content": "A previous answer."},
        {"role": "user", "content": "try again"},
    ])

    result = tool_registry.execute("conversation.inspect")

    assert result["active_topic"] == "give me a list of 100 books to read before i die"
    assert result["requested_count"] == 100
    assert "list" in result["requested_formats"]
    assert result["is_follow_up"] is True
    assert "system" not in str(result).lower()


def test_evidence_verify_tool_is_registered_and_returns_provenance(fake_ollama_chat):
    fake_ollama_chat.reply = "- Claim is [Unverified]."
    evidence = [{"url": "https://example.com", "content": "Source text."}]

    result = tool_registry.execute(
        "evidence.verify",
        answer_text="A drafted claim.",
        user_prompt="What is the claim?",
        evidence=evidence,
    )

    assert result["has_findings"] is True
    assert result["evidence_count"] == 1
    assert result["source_urls"] == ["https://example.com"]
    assert result["findings"] == fake_ollama_chat.reply


def test_knowledge_related_tool_returns_provenance(isolated_data_dir):
    webagent.record_to_knowledge_base("books.md", "Books about history and science.")

    result = tool_registry.execute("knowledge.related", topic="books", limit=1)

    assert len(result) == 1
    assert result[0]["path"] == "books.md"
    assert result[0]["provenance"]["origin"] == "saved-note"


def test_knowledge_forget_requires_confirmation_and_archives_source(isolated_data_dir):
    webagent.record_to_knowledge_base("remove-me.md", "Temporary note.")

    refused = tool_registry.execute("knowledge.forget", path="remove-me.md")
    assert refused["requires_confirmation"] is True
    assert (isolated_data_dir / "knowledge_base" / "remove-me.md").exists()

    removed = tool_registry.execute("knowledge.forget", path="remove-me.md", confirm=True)
    assert removed["removed"] is True
    assert not (isolated_data_dir / "knowledge_base" / "remove-me.md").exists()
    assert (isolated_data_dir / removed["archive_path"]).exists()


def test_knowledge_forget_rejects_path_traversal(isolated_data_dir):
    result = tool_registry.execute("knowledge.forget", path="../outside.txt", confirm=True)

    assert result["removed"] is False
    assert result["error"] == "source not found"


def test_repo_inspect_tool_is_registered_and_composes_audits(monkeypatch):
    monkeypatch.setattr(webagent, "audit_repository", lambda: "basic")
    monkeypatch.setattr(webagent, "audit_repository_advanced", lambda: "advanced")

    result = tool_registry.execute("repo.inspect")

    assert result == {"basic_audit": "basic", "advanced_audit": "advanced"}


def test_model_status_tool_is_bounded(monkeypatch):
    monkeypatch.setattr(webagent.context, "selected_model", "test-model")
    monkeypatch.setattr(webagent.context, "web_search_mode", False)
    monkeypatch.setattr(webagent.context, "deep_think_mode", True)

    result = tool_registry.execute("model.status")

    assert result["selected_model"] == "test-model"
    assert result["modes"] == {
        "web_search": False, "deep_think": True, "reasoning": False,
        "coding": False, "voice": False,
    }
    assert "assistant_convo" not in result
    assert "content" not in str(result)


def test_task_plan_tool_returns_bounded_json(fake_ollama_chat):
    fake_ollama_chat.reply = (
        '{"goal": "finish project", "steps": [{"title": "Run tests", '
        '"depends_on": [], "done": false}], "next_action": "Run tests"}'
    )

    result = tool_registry.execute("task.plan", goal="finish project", context="Python app")

    assert result == {
        "goal": "finish project",
        "steps": [{"title": "Run tests", "depends_on": [], "done": False}],
        "next_action": "Run tests",
    }


def test_web_fetch_tool_reaches_the_real_pipeline(monkeypatch):
    tool = tool_registry.get("web.fetch")
    assert tool is not None

    class FakeResponse:
        status_code = 200
        text = (
            "<html><body><p>hello from the real page - this paragraph is "
            "deliberately long enough to clear the extractor's 50-character "
            "minimum content threshold so it doesn't fall back to the "
            "'Limited content available' placeholder.</p></body></html>"
        )

    monkeypatch.setattr(webagent.requests, "get", lambda *a, **k: FakeResponse())

    result = tool_registry.execute("web.fetch", url="https://example.com")

    assert "hello from the real page" in result


def test_knowledge_tools_round_trip_through_the_real_filesystem(isolated_data_dir):
    """No internal dependency to mock here - search_knowledge_base and
    record_to_knowledge_base's only real dependency is the filesystem, which
    isolated_data_dir already redirects safely. Writing through knowledge.write
    and reading it back through knowledge.search proves both tools are wired
    to the same real, on-disk implementation."""
    assert tool_registry.get("knowledge.write") is not None
    assert tool_registry.get("knowledge.search") is not None

    tool_registry.execute("knowledge.write", filename="stoicism.md", content="Marcus Aurelius on impermanence.")

    results = tool_registry.execute("knowledge.search", topic="Marcus Aurelius")

    assert len(results) == 1
    filename, content = results[0]
    assert filename == "stoicism.md"
    assert "impermanence" in content


def test_subscriptions_list_tool_is_wired_to_the_real_subscriptions_module(isolated_data_dir):
    from core import subscriptions
    assert tool_registry.get("subscriptions.list") is not None
    subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})

    result = tool_registry.execute("subscriptions.list")

    assert result == subscriptions.list_subscriptions()
    assert result[0]["name"] == "Manchester United"


def test_cron_tools_round_trip_through_the_real_cron_functions(isolated_data_dir, no_real_crontab, monkeypatch):
    """cron.add/list/run/remove wired to webagent's real cron_add/
    cron_list_entries/run_cron_task_now/cron_remove - against a faked
    crontab (no_real_crontab) and an isolated tasks.json (isolated_data_dir),
    so this never touches the real system crontab."""
    for name in ("cron.list", "cron.add", "cron.edit", "cron.remove", "cron.run"):
        assert tool_registry.get(name) is not None

    monkeypatch.setattr(webagent, "news_command", lambda: [{"title": "fake headline"}])

    task_id, error = tool_registry.execute(
        "cron.add", schedule_fields=["0", "9", "*", "*", "*"], action_type="feature", action_payload="news",
    )
    assert error is None
    assert f"gnosis:{task_id}" in no_real_crontab["text"]

    entries, list_error = tool_registry.execute("cron.list")
    assert list_error is None
    assert len(entries) == 1

    ok, edit_error = tool_registry.execute("cron.edit", task_id=task_id, schedule_fields=["30", "10", "*", "*", "*"])
    assert ok is True
    assert edit_error is None

    success, output = tool_registry.execute("cron.run", task_id=task_id)
    assert success is True
    assert "fake headline" in output

    removed, remove_result = tool_registry.execute("cron.remove", index=1)
    assert removed is True


def test_git_tools_reach_a_real_git_repo(isolated_data_dir):
    """git.status/git.diff wired to webagent's real _git(), which runs an
    actual `git` subprocess scoped to core.config.project_root() -
    isolated_data_dir redirects that to a disposable repo, never the real
    Gnosis checkout."""
    assert tool_registry.get("git.status") is not None
    assert tool_registry.get("git.diff") is not None

    (isolated_data_dir / "a.py").write_text("x = 1\n")
    _run_git(isolated_data_dir, "init", "-q")
    _run_git(isolated_data_dir, "add", "-A")
    _run_git(isolated_data_dir, "commit", "-q", "-m", "initial")

    code, out, _ = tool_registry.execute("git.status")
    assert code == 0
    assert out.strip() == ""  # clean tree right after commit

    (isolated_data_dir / "a.py").write_text("x = 2\n")
    code, out, _ = tool_registry.execute("git.status")
    assert code == 0
    assert "a.py" in out

    code, out, _ = tool_registry.execute("git.diff")
    assert code == 0
    assert "-x = 1" in out
    assert "+x = 2" in out


def test_repo_audit_tool_reaches_the_real_function(isolated_data_dir):
    assert tool_registry.get("repo.audit") is not None
    (isolated_data_dir / "a.py").write_text("# TODO: fix this\nx = 1\n")

    report = tool_registry.execute("repo.audit")

    assert "Total files: 1" in report
    assert "a.py:1: # TODO: fix this" in report


def test_shell_sandboxed_run_tool_reaches_the_real_sandbox(isolated_data_dir):
    """shell.sandboxed_run wired to the real sandbox.commands.run_sandboxed_command,
    scoped to core.config.project_root() the same way git.status/git.diff are -
    isolated_data_dir redirects that to a disposable repo, never the real
    Gnosis checkout, and the command itself runs inside its own throwaway
    workspace, not even that disposable repo's own working directory."""
    assert tool_registry.get("shell.sandboxed_run") is not None

    (isolated_data_dir / "a.py").write_text("x = 1\n")
    _run_git(isolated_data_dir, "init", "-q")
    _run_git(isolated_data_dir, "add", "-A")
    _run_git(isolated_data_dir, "commit", "-q", "-m", "initial")

    code, out, err = tool_registry.execute("shell.sandboxed_run", command_name="git_status")

    assert code == 0
    assert out.strip() == ""

    code, out, err = tool_registry.execute("shell.sandboxed_run", command_name="nonexistent")
    assert code == 1
    assert "not an allowed" in err


def test_sandbox_session_and_filesystem_tools_reach_the_real_implementation(isolated_data_dir):
    """Full round trip through the registry: open a session, write a file
    into it, read it back, check its status with shell.sandboxed_run's
    workspace_id passthrough, then close with merge_back - proving all
    five tools (sandbox.open/close, fs.read/write, shell.sandboxed_run)
    are wired to the same real sandbox mechanism, not five independent
    stand-ins."""
    for name in ("sandbox.open", "sandbox.close", "fs.read", "fs.write"):
        assert tool_registry.get(name) is not None

    (isolated_data_dir / "a.py").write_text("x = 1\n")
    _run_git(isolated_data_dir, "init", "-q")
    _run_git(isolated_data_dir, "add", "-A")
    _run_git(isolated_data_dir, "commit", "-q", "-m", "initial")

    workspace_id = tool_registry.execute("sandbox.open")
    assert isinstance(workspace_id, str) and workspace_id

    tool_registry.execute("fs.write", workspace_id=workspace_id, path="a.py", content="x = 2\n")
    assert tool_registry.execute("fs.read", workspace_id=workspace_id, path="a.py") == "x = 2\n"
    # The live repo is untouched so far - only the open session's own copy changed.
    assert (isolated_data_dir / "a.py").read_text() == "x = 1\n"

    code, out, _ = tool_registry.execute(
        "shell.sandboxed_run", command_name="git_status", workspace_id=workspace_id,
    )
    assert code == 0
    assert "a.py" in out  # modified relative to the session's own checkout

    tool_registry.execute("sandbox.close", workspace_id=workspace_id, merge_back_paths=["a.py"])
    assert (isolated_data_dir / "a.py").read_text() == "x = 2\n"


def test_repo_audit_advanced_tool_reaches_the_real_function(isolated_data_dir):
    assert tool_registry.get("repo.audit_advanced") is not None
    (isolated_data_dir / "README.md").write_text("Just a title.\n")

    report = tool_registry.execute("repo.audit_advanced")

    assert "thin, consider expanding" in report
    assert "No CI configuration found." in report


def test_test_run_tool_reaches_the_real_test_suite(isolated_data_dir):
    """_run_self_improve_tests() shells out to a real subprocess running
    unittest discovery scoped to core.config.project_root() - isolated_data_dir
    redirects that to a disposable tests/ dir, never the real suite."""
    assert tool_registry.get("test.run") is not None
    tests_dir = isolated_data_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").write_text(
        "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
    )

    passed, output = tool_registry.execute("test.run")

    assert passed is True
    assert "Ran 1 test" in output


def test_design_tools_are_registered_and_reach_the_real_penpot_module(monkeypatch):
    """design.* tools were constructed with penpot.py's real functions at
    registration time - faking penpot.requests.post (rather than the
    tool's own execute()) and invoking through the registry proves that,
    the same way test_web_fetch_tool_reaches_the_real_pipeline does for
    webagent.requests."""
    for name in ("design.list_projects", "design.create_project", "design.list_files",
                 "design.create_file", "design.get_file", "design.add_board", "design.add_shape"):
        assert tool_registry.get(name) is not None

    monkeypatch.setenv("PENPOT_URL", "http://localhost:9001")
    monkeypatch.setenv("PENPOT_ACCESS_TOKEN", "test-token")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

        content = b"1"

    responses = iter([
        [{"id": "t1", "is-default": True}],  # get-teams
        [{"id": "p1", "name": "Website"}],  # get-projects
    ])
    monkeypatch.setattr(penpot.requests, "post", lambda *a, **k: FakeResponse(next(responses)))

    result = tool_registry.execute("design.list_projects")

    assert result == [{"id": "p1", "name": "Website"}]
