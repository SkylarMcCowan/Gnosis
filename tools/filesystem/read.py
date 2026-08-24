"""fs.read: read a file's content from within an open sandbox session's
workspace - never the live project tree directly, and never a path that
escapes the workspace boundary (sandbox.files._resolve_within_workspace).
"""
from tools.base import Permission, Tool


class FilesystemReadTool(Tool):
    name = "fs.read"
    description = "Read a file's content from an open sandbox workspace."
    parameters = {"workspace_id": "string", "path": "string, relative to the workspace root"}
    permission = Permission.SAFE

    def __init__(self, read_fn):
        self._read_fn = read_fn

    def execute(self, workspace_id, path):
        return self._read_fn(workspace_id, path)
