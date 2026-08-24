"""git.diff: show the working tree's uncommitted diff, wrapped as a Tool.
Fixed to `git diff` - see git_status.py's docstring for why these are
narrowly-scoped, single-command tools rather than one generic executor.
"""
from tools.base import Permission, Tool


class GitDiffTool(Tool):
    name = "git.diff"
    description = "Show the working tree's uncommitted diff (git diff)."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, git_fn):
        self._git_fn = git_fn

    def execute(self):
        return self._git_fn("diff")
