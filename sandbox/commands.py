"""A fixed, named allowlist of commands a caller can ask a Workspace to
run - never an arbitrary caller-supplied argument vector. Same discipline
as tools/shell/git_status.py and git_diff.py's fixed single commands, just
run inside an isolated workspace instead of the live checkout, and with
more than one command to choose from by name.
"""
import sys

from sandbox.sessions import get_session
from sandbox.workspace import Workspace

ALLOWED_COMMANDS = {
    "git_status": ("git", "status", "--porcelain"),
    "git_diff": ("git", "diff"),
    "run_tests": (sys.executable, "-m", "pytest", "-q"),
}


def run_sandboxed_command(command_name, repo_root, base_ref="HEAD", workspace_id=None):
    """Run one allowlisted command and return (returncode, stdout, stderr).

    Without `workspace_id`, this creates a fresh, throwaway Workspace that
    never outlives the call - there's nothing to merge back, since running
    a fixed read-only command is the whole point. With `workspace_id`, the
    command runs inside that already-open session instead (e.g. checking
    `git_status` on a workspace something else has been writing files into
    via sandbox.files, without creating yet another isolated copy just to
    ask that one question)."""
    if command_name not in ALLOWED_COMMANDS:
        return 1, "", f"'{command_name}' is not an allowed sandboxed command"
    if workspace_id is not None:
        workspace = get_session(workspace_id)
        if workspace is None:
            return 1, "", f"No open sandbox session {workspace_id!r}"
        return workspace.run(*ALLOWED_COMMANDS[command_name])
    with Workspace(repo_root, base_ref=base_ref) as workspace:
        return workspace.run(*ALLOWED_COMMANDS[command_name])
