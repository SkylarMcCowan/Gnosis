"""sandbox.close: destroy an open sandbox workspace, optionally merging
specific files back into the real repo first - the only way anything
written in a sandbox session ever reaches the live checkout.
REQUIRES_APPROVAL, not RESTRICTED: closing with merge_back_paths mutates
real, persistent project files, the same class of action cron.add/edit/
remove are classified this way for.
"""
from tools.base import Permission, Tool


class SandboxCloseTool(Tool):
    name = "sandbox.close"
    description = "Close a sandbox workspace, optionally merging specific files back into the real repo."
    parameters = {
        "workspace_id": "string",
        "merge_back_paths": "list[str], optional - files to copy into the real repo before destroying the workspace",
    }
    permission = Permission.REQUIRES_APPROVAL

    def __init__(self, close_fn):
        self._close_fn = close_fn

    def execute(self, workspace_id, merge_back_paths=None):
        return self._close_fn(workspace_id, merge_back_paths=merge_back_paths)
