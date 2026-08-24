"""shell.sandboxed_run: run one allowlisted command inside an isolated
git worktree (sandbox.workspace.Workspace) rather than the live checkout -
Phase 2's "Shell execution becomes a tool" item, deliberately deferred
there until a sandbox (Phase 10) existed to bound it. Still not a generic
`shell.run(*args)` passthrough: the caller names one of a small, fixed set
of commands (sandbox.commands.ALLOWED_COMMANDS), never supplies arbitrary
argv. Without `workspace_id` this runs in a fresh, throwaway workspace;
with one (from `sandbox.open`), it runs inside that already-open session
instead - e.g. checking `git_status` on a workspace `fs.write` has been
building up.
"""
from tools.base import Permission, Tool


class ShellSandboxedRunTool(Tool):
    name = "shell.sandboxed_run"
    description = "Run one allowlisted command (e.g. 'run_tests') inside an isolated workspace."
    parameters = {
        "command_name": "string (one of sandbox.commands.ALLOWED_COMMANDS's keys)",
        "workspace_id": "string, optional (an already-open session from sandbox.open)",
    }
    permission = Permission.RESTRICTED

    def __init__(self, run_fn):
        self._run_fn = run_fn

    def execute(self, command_name, workspace_id=None):
        return self._run_fn(command_name, workspace_id=workspace_id)
