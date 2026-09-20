"""repo.inspect: structured read-only repository inspection."""
from tools.base import Permission, Tool


class RepoInspectTool(Tool):
    name = "repo.inspect"
    description = "Inspect repository structure, audit findings, documentation, and test readiness."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, inspect_fn):
        self._inspect_fn = inspect_fn

    def execute(self):
        return self._inspect_fn()
