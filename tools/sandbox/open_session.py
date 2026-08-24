"""sandbox.open: create an isolated Workspace and keep it open, returning
an id later calls (fs.read/fs.write/shell.sandboxed_run/sandbox.close)
address it by. RESTRICTED - creates a real git worktree and consumes real
disk/subprocess resources, even though nothing outside it is touched yet.
"""
from tools.base import Permission, Tool


class SandboxOpenTool(Tool):
    name = "sandbox.open"
    description = "Open an isolated sandbox workspace and return its session id."
    parameters = {}
    permission = Permission.RESTRICTED

    def __init__(self, open_fn):
        self._open_fn = open_fn

    def execute(self):
        return self._open_fn()
