"""Regression tests for builder/pipeline.py's run_tool_generation_cycle -
the full CAPABILITY GAP -> ... -> PROPOSAL orchestration. Real sandbox
validation against a real, disposable git repo; fake coding_chat_fn (no
real model calls).
"""
import os
import re
import subprocess

import pytest

from builder.pipeline import run_tool_generation_cycle
from core.activity_log import load_activity
from memory.experience import build_experience, load_experiences, record_experience

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


@pytest.fixture
def git_repo(isolated_data_dir):
    repo_dir = isolated_data_dir / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text("x = 1\n")
    tools_dir = repo_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "registry.py").write_text(
        "class ToolRegistry:\n"
        "    def __init__(self):\n"
        "        self._tools = {}\n"
        "    def execute(self, name, **kwargs):\n"
        "        return None\n\n"
        "registry = ToolRegistry()\n"
    )
    _run_git(repo_dir, "init", "-q")
    _run_git(repo_dir, "add", "-A")
    _run_git(repo_dir, "commit", "-q", "-m", "initial")
    return repo_dir


def test_reports_nothing_to_generate_when_no_findings_exist(isolated_data_dir):
    report = run_tool_generation_cycle(lambda s, u: "unused", repo_root="/unused", available_tools=[])
    assert "No recurring capability gap found" in report
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is None
    assert experiences[0]["agent"] == "tool-generator"


def _seed_repeated_failure(agent=None):
    for _ in range(2):
        record_experience(build_experience(goal="fix a", success=False, agent=agent))


def _expected_header(system_prompt):
    """Both generation prompts tell the model exactly what `### <path>`
    header to use - extract it rather than guess the slug independently,
    so these tests stay correct regardless of how slug_for_gap derives it
    from a given finding's summary text."""
    match = re.search(r"### (\S+\.py)", system_prompt)
    assert match, "prompt did not contain an expected '### <path>.py' header"
    return match.group(1)


def test_reports_no_skill_generated_when_the_model_response_cannot_be_parsed(isolated_data_dir):
    _seed_repeated_failure()
    report = run_tool_generation_cycle(lambda s, u: "not parseable", repo_root="/unused", available_tools=[])
    assert "No skill generated" in report
    experiences = load_experiences()
    assert experiences[-1]["success"] is False


def test_reports_no_tests_generated_when_the_second_model_call_cannot_be_parsed(isolated_data_dir):
    _seed_repeated_failure()
    calls = {"n": 0}

    def fake_chat(system_prompt, user_prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            header = _expected_header(system_prompt)
            return f"### {header}\n```python\nclass FixASkill:\n    pass\n```\n"
        return "not parseable"

    report = run_tool_generation_cycle(fake_chat, repo_root="/unused", available_tools=[])
    assert "No tests generated" in report
    experiences = load_experiences()
    assert experiences[-1]["success"] is False


def test_full_cycle_writes_a_passing_proposal(isolated_data_dir, git_repo):
    _seed_repeated_failure()

    def fake_chat(system_prompt, user_prompt):
        if "Reviewer" in system_prompt:
            return "[OK] fine"
        header = _expected_header(system_prompt)
        if "pytest" in system_prompt:
            return (
                f"### {header}\n```python\n"
                "from generated_skill import FixASkill\n\n"
                "def test_execute_returns_true():\n"
                "    assert FixASkill().execute() is True\n"
                "```\n"
            )
        return f"### {header}\n```python\nclass FixASkill:\n    def execute(self, **kwargs):\n        return True\n```\n"

    report = run_tool_generation_cycle(fake_chat, repo_root=str(git_repo), available_tools=[("web.search", "search")])

    assert "tests passed" in report
    assert "Engineering team recommendation: Looks reasonable" in report
    experiences = load_experiences()
    assert experiences[-1]["success"] is True
    skill_created = load_activity(event_name="SKILL_CREATED")
    assert len(skill_created) == 1
    assert skill_created[0]["passed"] is True

    proposals_dir = isolated_data_dir / "gnosis_workspace" / "proposals"
    proposal_dirs = list(proposals_dir.iterdir())
    assert len(proposal_dirs) == 1
    assert any(f.suffix == ".py" and f.name.startswith("generated_") for f in proposal_dirs[0].iterdir())
    report_text = (proposal_dirs[0] / "report.md").read_text()
    assert "Engineering team review" in report_text
    # Never registered anywhere.
    import webagent
    assert len(webagent.skill_registry.list_namespace("generated")) == 0


def test_full_cycle_writes_a_failing_proposal_when_generated_tests_fail(isolated_data_dir, git_repo):
    _seed_repeated_failure()

    def fake_chat(system_prompt, user_prompt):
        if "Reviewer" in system_prompt:
            return "[OK] fine"
        header = _expected_header(system_prompt)
        if "pytest" in system_prompt:
            return (
                f"### {header}\n```python\n"
                "from generated_skill import FixASkill\n\n"
                "def test_execute_returns_true():\n"
                "    assert FixASkill().execute() is False\n"  # deliberately wrong
                "```\n"
            )
        return f"### {header}\n```python\nclass FixASkill:\n    def execute(self, **kwargs):\n        return True\n```\n"

    report = run_tool_generation_cycle(fake_chat, repo_root=str(git_repo), available_tools=[])

    assert "tests FAILED" in report
    assert "Engineering team recommendation: NOT RECOMMENDED" in report
    experiences = load_experiences()
    assert experiences[-1]["success"] is False
    proposals_dir = isolated_data_dir / "gnosis_workspace" / "proposals"
    assert len(list(proposals_dir.iterdir())) == 1


def test_uses_the_most_frequent_finding_when_several_exist(isolated_data_dir):
    for _ in range(2):
        record_experience(build_experience(goal="fix a", success=False, agent="self-improve"))
    for _ in range(4):
        record_experience(build_experience(goal="fix b", success=False, agent="self-improve"))

    run_tool_generation_cycle(
        lambda s, u: "not parseable", repo_root="/unused", available_tools=[], agent="self-improve",
    )

    experiences = load_experiences()
    assert "fix b" in experiences[-1]["goal"]  # 4 failures outranks 2
