"""Regression tests for sandbox/sessions.py's open/close session registry -
real git worktree operations against a real, disposable git repo.
"""
import os
import subprocess

import pytest

from sandbox.sessions import close_session, get_session, open_session

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


def test_open_session_returns_a_usable_id(git_repo):
    workspace_id = open_session(str(git_repo))
    try:
        workspace = get_session(workspace_id)
        assert workspace is not None
        assert os.path.isdir(workspace.path)
    finally:
        close_session(workspace_id)


def test_close_session_removes_the_workspace(git_repo):
    workspace_id = open_session(str(git_repo))
    workspace = get_session(workspace_id)
    path = workspace.path

    close_session(workspace_id)

    assert not os.path.exists(path)
    assert get_session(workspace_id) is None


def test_close_session_merges_back_specified_files(git_repo):
    workspace_id = open_session(str(git_repo))
    workspace = get_session(workspace_id)
    with open(os.path.join(workspace.path, "a.py"), "w") as f:
        f.write("x = 42\n")

    close_session(workspace_id, merge_back_paths=["a.py"])

    assert (git_repo / "a.py").read_text() == "x = 42\n"


def test_close_session_without_merge_back_discards_changes(git_repo):
    workspace_id = open_session(str(git_repo))
    workspace = get_session(workspace_id)
    with open(os.path.join(workspace.path, "a.py"), "w") as f:
        f.write("x = 999\n")

    close_session(workspace_id)

    assert (git_repo / "a.py").read_text() == "x = 1\n"


def test_close_session_raises_for_an_unknown_id():
    with pytest.raises(KeyError):
        close_session("nonexistent-id")


def test_close_session_twice_raises_the_second_time(git_repo):
    workspace_id = open_session(str(git_repo))
    close_session(workspace_id)
    with pytest.raises(KeyError):
        close_session(workspace_id)


def test_two_open_sessions_are_independent(git_repo):
    id_a = open_session(str(git_repo))
    id_b = open_session(str(git_repo))
    try:
        workspace_a = get_session(id_a)
        workspace_b = get_session(id_b)
        assert workspace_a.path != workspace_b.path
        with open(os.path.join(workspace_a.path, "a.py"), "w") as f:
            f.write("x = 111\n")
        assert open(os.path.join(workspace_b.path, "a.py")).read() == "x = 1\n"
    finally:
        close_session(id_a)
        close_session(id_b)
