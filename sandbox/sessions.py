"""A registry of *open* Workspace sessions - the piece Phase 10's own
write-up flagged as missing: `Workspace` is a context manager (create, use,
destroy, all in one `with` block), which is fine for shell.sandboxed_run's
single allowlisted command but not for fs.read/fs.write, which need to
operate on the *same* isolated copy across several separate tool calls
(write a file, then read it back, then decide whether to keep it) before
anything gets merged back or discarded.

`open_session` enters a Workspace and keeps it open past this call;
`close_session` is the only way it ever gets cleaned up. A session left
open forever (a caller that opens one and never closes it, or a crash)
does *not* linger as a git-status-blocking problem for self-improve or
anything else, since `gnosis_workspace/` is already gitignored for exactly
this kind of orphaning - but it does mean the workspace directory itself
sits on disk until something closes it or the directory is cleaned up by
hand. No automatic expiry is built - there's no real usage pattern yet to
size a timeout against, and a guessed one would just be a different kind
of bug.
"""
import threading

from sandbox.workspace import Workspace

_sessions = {}
_lock = threading.Lock()


def open_session(repo_root, base_ref="HEAD", **kwargs):
    """Create and enter a Workspace, keep it open, and return its id -
    later calls address it by that id instead of holding a Python
    reference across separate tool invocations."""
    workspace = Workspace(repo_root, base_ref=base_ref, **kwargs)
    workspace.__enter__()
    with _lock:
        _sessions[workspace.run_id] = workspace
    return workspace.run_id


def get_session(workspace_id):
    with _lock:
        return _sessions.get(workspace_id)


def close_session(workspace_id, merge_back_paths=None, dest_root=None):
    """Merge back the given paths (if any), then destroy the workspace.
    Raises KeyError for an unknown/already-closed id, so a caller can't
    silently no-op on a typo'd id."""
    with _lock:
        workspace = _sessions.pop(workspace_id, None)
    if workspace is None:
        raise KeyError(f"No open sandbox session {workspace_id!r}")
    if merge_back_paths:
        workspace.merge_back(merge_back_paths, dest_root=dest_root)
    workspace.__exit__(None, None, None)
