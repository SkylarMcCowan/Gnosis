"""Regression tests for sandbox/commands.py's fixed command allowlist -
real git worktree operations against a real, disposable git repo.
"""
import os
import subprocess

import pytest

from sandbox.commands import ALLOWED_COMMANDS, run_sandboxed_command

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
    _run_git(repo_dir, "init", "-q")
    _run_git(repo_dir, "add", "-A")
    _run_git(repo_dir, "commit", "-q", "-m", "initial")
    return repo_dir


def test_run_sandboxed_command_rejects_an_unknown_command_name(git_repo):
    code, out, err = run_sandboxed_command("nonexistent_command", repo_root=str(git_repo))
    assert code == 1
    assert "not an allowed" in err


def test_run_sandboxed_command_runs_git_status_inside_an_isolated_workspace(git_repo):
    code, out, err = run_sandboxed_command("git_status", repo_root=str(git_repo))
    assert code == 0
    assert out.strip() == ""  # freshly checked out, nothing uncommitted


def test_run_sandboxed_command_runs_tests_inside_the_workspace(git_repo):
    tests_dir = git_repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("def test_passes():\n    assert 1 + 1 == 2\n")
    _run_git(git_repo, "add", "-A")
    _run_git(git_repo, "commit", "-q", "-m", "add a test")

    code, out, err = run_sandboxed_command("run_tests", repo_root=str(git_repo))

    assert code == 0
    assert "1 passed" in out


def test_run_sandboxed_command_never_leaves_a_workspace_behind(git_repo):
    from sandbox.workspace import _workspace_runs_dir
    run_sandboxed_command("git_status", repo_root=str(git_repo))
    runs_dir = _workspace_runs_dir()
    assert not os.path.exists(runs_dir) or os.listdir(runs_dir) == []


def test_allowed_commands_are_all_fixed_tuples_not_caller_supplied():
    for name, command in ALLOWED_COMMANDS.items():
        assert isinstance(command, tuple)
        assert all(isinstance(part, str) for part in command)
