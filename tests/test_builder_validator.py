"""Regression tests for builder/validator.py - the one place in the whole
generation pipeline that actually runs model-written code. Real git
worktree + real pytest subprocess against a real, disposable repo (never
the real Gnosis checkout). The security test at the bottom is the most
important one in this file: it proves a generated test cannot reach a
real tool, even one classified SAFE, no matter what it tries.
"""
import os
import subprocess

import pytest

from builder.validator import validate_generated_skill
from core.activity_log import load_activity

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
    """A disposable repo that also carries a minimal, real-shaped
    tools.registry module (a ToolRegistry with an execute() method and a
    module-level `registry` singleton, plus one real, harmless tool
    registered as "git.status") - just enough for a sandboxed generated
    test's `from tools.registry import registry as tool_registry` and the
    conftest.py safety net's monkeypatch target to resolve exactly like
    they would against the real project, without needing the real
    checkout at all."""
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
        "    def register(self, name, fn):\n"
        "        self._tools[name] = fn\n"
        "    def execute(self, name, **kwargs):\n"
        "        return self._tools[name](**kwargs)\n\n"
        "registry = ToolRegistry()\n"
        "registry.register('git.status', lambda: (0, '', ''))\n"
    )
    _run_git(repo_dir, "init", "-q")
    _run_git(repo_dir, "add", "-A")
    _run_git(repo_dir, "commit", "-q", "-m", "initial")
    return repo_dir


_PASSING_SKILL = "class GapSkill:\n    def execute(self, **kwargs):\n        return 42\n"
_PASSING_TEST = (
    "from generated_skill import GapSkill\n\n"
    "def test_execute_returns_42():\n"
    "    assert GapSkill().execute() == 42\n"
)


def test_validate_generated_skill_reports_passed_for_a_genuinely_passing_test(git_repo, isolated_data_dir):
    passed, output = validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", _PASSING_TEST)
    assert passed is True
    assert "1 passed" in output
    assert len(load_activity(event_name="TEST_PASSED")) == 1


def test_validate_generated_skill_publishes_test_failed_on_a_compile_error(git_repo, isolated_data_dir):
    validate_generated_skill(str(git_repo), "class GapSkill(:\n    pass\n", "tests/test_gap.py", _PASSING_TEST)
    assert len(load_activity(event_name="TEST_FAILED")) == 1


def test_validate_generated_skill_reports_failed_for_a_failing_test(git_repo):
    failing_test = (
        "from generated_skill import GapSkill\n\n"
        "def test_execute_returns_the_wrong_thing():\n"
        "    assert GapSkill().execute() == 999\n"
    )
    passed, output = validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", failing_test)
    assert passed is False
    assert "1 failed" in output


def test_validate_generated_skill_reports_a_skill_compile_error(git_repo):
    broken_skill = "class GapSkill(:\n    pass\n"  # syntax error
    passed, output = validate_generated_skill(str(git_repo), broken_skill, "tests/test_gap.py", _PASSING_TEST)
    assert passed is False
    assert "does not compile" in output


def test_validate_generated_skill_reports_a_test_compile_error(git_repo):
    broken_test = "def test_x(:\n    pass\n"  # syntax error
    passed, output = validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", broken_test)
    assert passed is False
    assert "does not compile" in output


def test_validate_generated_skill_never_leaves_a_workspace_behind(git_repo):
    validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", _PASSING_TEST)
    runs_dir = git_repo / "gnosis_workspace" / "runs"
    assert not runs_dir.exists() or os.listdir(runs_dir) == []


def test_validate_generated_skill_blocks_a_real_tool_execution_attempt(git_repo):
    """The critical security property: a generated test that tries to
    reach a REAL tool - even git.status, which is itself classified SAFE
    - must never succeed. The safety net blocks every real tool call
    unconditionally; it does not try to judge which ones are "safe
    enough" to let through."""
    test_code = (
        "def test_calls_a_real_tool():\n"
        "    from tools.registry import registry as tool_registry\n"
        "    tool_registry.execute('git.status')\n"
    )
    passed, output = validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", test_code)
    assert passed is False
    assert "Blocked a real tool_registry.execute" in output


def test_validate_generated_skill_blocks_even_when_the_test_never_faked_anything(git_repo):
    """Same property, phrased the other way: a test that does exactly what
    the generation prompt tells it NOT to do (skip the monkeypatch
    entirely) is still safe to run, because the block doesn't depend on
    the generated test cooperating."""
    reckless_test = (
        "from generated_skill import GapSkill\n"
        "from tools.registry import registry as tool_registry\n\n"
        "def test_no_mocking_at_all():\n"
        "    tool_registry.execute('cron.add', schedule_fields=['0','9','*','*','*'], "
        "action_type='prompt', action_payload='pwned')\n"
    )
    passed, output = validate_generated_skill(str(git_repo), _PASSING_SKILL, "tests/test_gap.py", reckless_test)
    assert passed is False
    assert "Blocked a real tool_registry.execute" in output
