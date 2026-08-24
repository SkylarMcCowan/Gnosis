"""fs.write: write a file's content within an open sandbox session's
workspace - never the live project tree directly. RESTRICTED rather than
SAFE, matching knowledge.write's classification: it writes to disk, even
though what it writes to is a throwaway, isolated copy rather than the
live repo (that boundary is what makes this safe enough to build at all -
see tools/filesystem/__init__.py).
"""
from tools.base import Permission, Tool


class FilesystemWriteTool(Tool):
    name = "fs.write"
    description = "Write content to a file inside an open sandbox workspace."
    parameters = {
        "workspace_id": "string", "path": "string, relative to the workspace root", "content": "string",
    }
    permission = Permission.RESTRICTED

    def __init__(self, write_fn):
        self._write_fn = write_fn

    def execute(self, workspace_id, path, content):
        return self._write_fn(workspace_id, path, content)
