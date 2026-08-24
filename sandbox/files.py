"""Filesystem access bounded to an open sandbox session's own directory -
the "allowed directories" half of Phase 2's deferred fs.read/fs.write,
finally unblocked now that a real sandbox exists. Every path is resolved
and checked against the session's workspace root before any read/write
happens, so a relative path can't escape it (`../../etc/passwd` and
similar).
"""
import os

from sandbox.sessions import get_session


def _resolve_within_workspace(workspace, relative_path):
    workspace_root = os.path.realpath(workspace.path)
    full_path = os.path.realpath(os.path.join(workspace_root, relative_path))
    if full_path != workspace_root and not full_path.startswith(workspace_root + os.sep):
        raise ValueError(f"path {relative_path!r} escapes the sandbox workspace boundary")
    return full_path


def _require_session(workspace_id):
    workspace = get_session(workspace_id)
    if workspace is None:
        raise KeyError(f"No open sandbox session {workspace_id!r}")
    return workspace


def read_file(workspace_id, path):
    workspace = _require_session(workspace_id)
    full_path = _resolve_within_workspace(workspace, path)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(workspace_id, path, content):
    workspace = _require_session(workspace_id)
    full_path = _resolve_within_workspace(workspace, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True
