"""Regression tests for tools/shell/git_status.py, git_diff.py, test_run.py,
and tools/repository/audit.py + audit_advanced.py - Tool classes in
isolation, constructed with a fake callable. Real wiring against webagent's
actual git/test/audit functions is in tests/test_tools_wiring.py.
"""
from tools.base import Permission
from tools.repository.audit import RepoAuditTool
from tools.repository.audit_advanced import RepoAuditAdvancedTool
from tools.shell.git_diff import GitDiffTool
from tools.shell.git_status import GitStatusTool
from tools.shell.sandboxed_run import ShellSandboxedRunTool
from tools.shell.test_run import TestRunTool


def test_git_status_calls_git_fn_with_fixed_args():
    calls = []
    tool = GitStatusTool(lambda *args: calls.append(args) or (0, "", ""))
    assert tool.execute() == (0, "", "")
    assert calls == [("status", "--porcelain")]


def test_git_status_metadata():
    tool = GitStatusTool(lambda *a: (0, "", ""))
    assert tool.name == "git.status"
    assert tool.permission == Permission.SAFE


def test_git_diff_calls_git_fn_with_fixed_args():
    calls = []
    tool = GitDiffTool(lambda *args: calls.append(args) or (0, "diff text", ""))
    assert tool.execute() == (0, "diff text", "")
    assert calls == [("diff",)]


def test_git_diff_metadata():
    tool = GitDiffTool(lambda *a: (0, "", ""))
    assert tool.name == "git.diff"
    assert tool.permission == Permission.SAFE


def test_test_run_forwards_to_run_fn():
    tool = TestRunTool(lambda: (True, "5 passed"))
    assert tool.execute() == (True, "5 passed")


def test_test_run_metadata():
    tool = TestRunTool(lambda: (True, ""))
    assert tool.name == "test.run"
    assert tool.permission == Permission.RESTRICTED


def test_repo_audit_forwards_to_audit_fn():
    tool = RepoAuditTool(lambda: "Total files: 42")
    assert tool.execute() == "Total files: 42"


def test_repo_audit_metadata():
    tool = RepoAuditTool(lambda: "")
    assert tool.name == "repo.audit"
    assert tool.permission == Permission.SAFE


def test_repo_audit_advanced_forwards_to_audit_fn():
    tool = RepoAuditAdvancedTool(lambda: "README quality: ...")
    assert tool.execute() == "README quality: ..."


def test_repo_audit_advanced_metadata():
    tool = RepoAuditAdvancedTool(lambda: "")
    assert tool.name == "repo.audit_advanced"
    assert tool.permission == Permission.SAFE


def test_shell_sandboxed_run_forwards_the_command_name():
    calls = []
    tool = ShellSandboxedRunTool(
        lambda command_name, workspace_id=None: calls.append((command_name, workspace_id)) or (0, "ok", "")
    )
    assert tool.execute("git_status") == (0, "ok", "")
    assert calls == [("git_status", None)]


def test_shell_sandboxed_run_forwards_an_explicit_workspace_id():
    calls = []
    tool = ShellSandboxedRunTool(
        lambda command_name, workspace_id=None: calls.append((command_name, workspace_id)) or (0, "ok", "")
    )
    tool.execute("git_status", workspace_id="workspace-123")
    assert calls == [("git_status", "workspace-123")]


def test_shell_sandboxed_run_metadata():
    tool = ShellSandboxedRunTool(lambda command_name: (0, "", ""))
    assert tool.name == "shell.sandboxed_run"
    assert tool.permission == Permission.RESTRICTED
