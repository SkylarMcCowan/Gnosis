"""git.status: report the working tree's dirty state, wrapped as a Tool.

Deliberately fixed to `git status --porcelain`, not a raw pass-through of
_git(*args) - _git() itself can run *any* git subcommand (including
`checkout`, `reset --hard`, `push --force`), and handing that out under one
generic tool name would just be tools/shell/'s "nothing should default to
SAFE" warning ignored. Each git capability gets its own narrowly-scoped
tool with a fixed command, the same way cron got five specific verbs
instead of one generic executor.
"""
from tools.base import Permission, Tool


class GitStatusTool(Tool):
    name = "git.status"
    description = "Report the working tree's dirty state (git status --porcelain)."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, git_fn):
        self._git_fn = git_fn

    def execute(self):
        return self._git_fn("status", "--porcelain")
