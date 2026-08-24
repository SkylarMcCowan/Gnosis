"""Regression tests for tools/filesystem/read.py and write.py - Tool
classes in isolation, constructed with a fake callable. Real wiring
against the actual sandboxed filesystem implementation is in
tests/test_tools_wiring.py.
"""
from tools.base import Permission
from tools.filesystem.read import FilesystemReadTool
from tools.filesystem.write import FilesystemWriteTool


def test_fs_read_forwards_workspace_id_and_path():
    calls = []
    tool = FilesystemReadTool(lambda workspace_id, path: calls.append((workspace_id, path)) or "content")
    assert tool.execute("workspace-123", "a.py") == "content"
    assert calls == [("workspace-123", "a.py")]


def test_fs_read_metadata():
    tool = FilesystemReadTool(lambda workspace_id, path: "")
    assert tool.name == "fs.read"
    assert tool.permission == Permission.SAFE


def test_fs_write_forwards_workspace_id_path_and_content():
    calls = []
    tool = FilesystemWriteTool(lambda workspace_id, path, content: calls.append((workspace_id, path, content)))
    tool.execute("workspace-123", "a.py", "x = 1\n")
    assert calls == [("workspace-123", "a.py", "x = 1\n")]


def test_fs_write_metadata():
    tool = FilesystemWriteTool(lambda workspace_id, path, content: True)
    assert tool.name == "fs.write"
    assert tool.permission == Permission.RESTRICTED
