"""Regression tests for sandbox/workspace.py's Workspace - real git
worktree operations against a real, disposable git repo (never the real
Gnosis checkout). Same env/helper pattern as test_tools_wiring.py's git
tests and test_selfimprove.py's selfimprove_repo fixture.
"""
import os
import subprocess
import time

import pytest

from sandbox.workspace import Workspace

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


def test_workspace_creates_an_isolated_checkout(git_repo):
    with Workspace(str(git_repo)) as ws:
        assert os.path.isdir(ws.path)
        assert ws.path != str(git_repo)
        assert (open(os.path.join(ws.path, "a.py")).read()) == "x = 1\n"


def test_workspace_edits_never_touch_the_live_repo(git_repo):
    with Workspace(str(git_repo)) as ws:
        with open(os.path.join(ws.path, "a.py"), "w") as f:
            f.write("x = 999\n")
        assert open(os.path.join(ws.path, "a.py")).read() == "x = 999\n"
    assert (git_repo / "a.py").read_text() == "x = 1\n"


def test_workspace_cleanup_removes_the_directory_on_exit(git_repo):
    with Workspace(str(git_repo)) as ws:
        path = ws.path
        assert os.path.isdir(path)
    assert not os.path.exists(path)


def test_workspace_cleanup_happens_even_on_exception(git_repo):
    path = None
    with pytest.raises(ValueError):
        with Workspace(str(git_repo)) as ws:
            path = ws.path
            raise ValueError("boom")
    assert not os.path.exists(path)


def test_merge_back_copies_a_file_to_the_live_repo(git_repo):
    with Workspace(str(git_repo)) as ws:
        with open(os.path.join(ws.path, "a.py"), "w") as f:
            f.write("x = 42\n")
        ws.merge_back(["a.py"])
    assert (git_repo / "a.py").read_text() == "x = 42\n"


def test_merge_back_creates_missing_parent_directories(git_repo):
    with Workspace(str(git_repo)) as ws:
        os.makedirs(os.path.join(ws.path, "tests"), exist_ok=True)
        with open(os.path.join(ws.path, "tests", "test_new.py"), "w") as f:
            f.write("def test_x(): pass\n")
        ws.merge_back(["tests/test_new.py"])
    assert (git_repo / "tests" / "test_new.py").read_text() == "def test_x(): pass\n"


def test_run_executes_inside_the_workspace_directory(git_repo):
    with Workspace(str(git_repo)) as ws:
        code, out, _ = ws.run("cat", "a.py")
        assert code == 0
        assert out == "x = 1\n"


def test_run_enforces_a_timeout(git_repo):
    with Workspace(str(git_repo)) as ws:
        started = time.monotonic()
        code, out, err = ws.run("sleep", "5", timeout=1)
        elapsed = time.monotonic() - started
    assert code != 0
    assert "timed out" in err
    assert elapsed < 4  # well under the 5s sleep - the timeout actually fired


def test_workspace_raises_a_clear_error_for_a_non_git_directory(isolated_data_dir):
    not_a_repo = isolated_data_dir / "plain_dir"
    not_a_repo.mkdir()
    with pytest.raises(RuntimeError):
        with Workspace(str(not_a_repo)):
            pass
