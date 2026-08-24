"""Regression tests for tools/sandbox/open_session.py and
close_session.py - Tool classes in isolation, constructed with a fake
callable. Real wiring against the actual sandbox session registry is in
tests/test_tools_wiring.py.
"""
from tools.base import Permission
from tools.sandbox.close_session import SandboxCloseTool
from tools.sandbox.open_session import SandboxOpenTool


def test_sandbox_open_forwards_to_open_fn():
    tool = SandboxOpenTool(lambda: "workspace-123")
    assert tool.execute() == "workspace-123"


def test_sandbox_open_metadata():
    tool = SandboxOpenTool(lambda: "")
    assert tool.name == "sandbox.open"
    assert tool.permission == Permission.RESTRICTED


def test_sandbox_close_forwards_workspace_id_and_merge_back_paths():
    calls = []
    tool = SandboxCloseTool(lambda workspace_id, merge_back_paths=None: calls.append((workspace_id, merge_back_paths)))
    tool.execute("workspace-123", merge_back_paths=["a.py"])
    assert calls == [("workspace-123", ["a.py"])]


def test_sandbox_close_defaults_merge_back_paths_to_none():
    calls = []
    tool = SandboxCloseTool(lambda workspace_id, merge_back_paths=None: calls.append(merge_back_paths))
    tool.execute("workspace-123")
    assert calls == [None]


def test_sandbox_close_metadata():
    tool = SandboxCloseTool(lambda workspace_id, merge_back_paths=None: None)
    assert tool.name == "sandbox.close"
    assert tool.permission == Permission.REQUIRES_APPROVAL
