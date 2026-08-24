"""Regression tests for sandbox/files.py - fs.read/fs.write's real
implementation, path-traversal protected, bounded to an open sandbox
session's workspace directory.
"""
import os
import subprocess

import pytest

from sandbox.files import read_file, write_file
from sandbox.sessions import close_session, open_session

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
def open_workspace(isolated_data_dir):
    repo_dir = isolated_data_dir / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text("x = 1\n")
    _run_git(repo_dir, "init", "-q")
    _run_git(repo_dir, "add", "-A")
    _run_git(repo_dir, "commit", "-q", "-m", "initial")
    workspace_id = open_session(str(repo_dir))
    yield workspace_id, repo_dir
    try:
        close_session(workspace_id)
    except KeyError:
        pass  # already closed by the test itself


def test_read_file_reads_the_checked_out_content(open_workspace):
    workspace_id, _ = open_workspace
    assert read_file(workspace_id, "a.py") == "x = 1\n"


def test_write_then_read_round_trips_within_the_same_session(open_workspace):
    workspace_id, _ = open_workspace
    write_file(workspace_id, "a.py", "x = 2\n")
    assert read_file(workspace_id, "a.py") == "x = 2\n"


def test_write_never_touches_the_live_repo_until_merged_back(open_workspace):
    workspace_id, repo_dir = open_workspace
    write_file(workspace_id, "a.py", "x = 999\n")
    assert (repo_dir / "a.py").read_text() == "x = 1\n"


def test_write_creates_missing_parent_directories(open_workspace):
    workspace_id, _ = open_workspace
    write_file(workspace_id, "new/nested/file.txt", "hello")
    assert read_file(workspace_id, "new/nested/file.txt") == "hello"


def test_read_rejects_a_path_traversal_attempt(open_workspace):
    workspace_id, _ = open_workspace
    with pytest.raises(ValueError, match="escapes"):
        read_file(workspace_id, "../../../etc/passwd")


def test_write_rejects_a_path_traversal_attempt(open_workspace):
    workspace_id, _ = open_workspace
    with pytest.raises(ValueError, match="escapes"):
        write_file(workspace_id, "../outside.py", "x = 1\n")


def test_read_raises_for_an_unknown_session():
    with pytest.raises(KeyError):
        read_file("nonexistent-id", "a.py")


def test_write_raises_for_an_unknown_session():
    with pytest.raises(KeyError):
        write_file("nonexistent-id", "a.py", "content")


def test_read_raises_for_a_closed_session(open_workspace):
    workspace_id, _ = open_workspace
    close_session(workspace_id)
    with pytest.raises(KeyError):
        read_file(workspace_id, "a.py")
