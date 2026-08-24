"""Workspace: an isolated `git worktree` that risky file edits and fixed,
allowlisted commands run inside of, instead of touching the live checkout
directly. Nothing outside `self.path` is ever written to unless
`merge_back()` is called explicitly - that's the whole safety property.

Git worktree, not a full copy: `git worktree add --detach <path> <ref>`
checks out the same commit into a second, independent working directory
that shares the main repo's object store - real git isolation (a commit
made or a file edited in the workspace never touches the main working
tree or index) without duplicating the whole repository on disk.
"""
import os
import shutil
import subprocess
import uuid

from core import config as core_config

try:
    import resource
except ImportError:  # Windows has no `resource` module
    resource = None

DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MEMORY_LIMIT_MB = 1024


def _workspace_runs_dir():
    return core_config.path("gnosis_workspace", "runs")


def _memory_limit_preexec_fn(memory_limit_mb):
    if resource is None or memory_limit_mb is None:
        return None
    limit_bytes = memory_limit_mb * 1024 * 1024

    def _set_limit():
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except (ValueError, OSError):
            pass  # best-effort - isolation still holds via the worktree boundary alone

    return _set_limit


class Workspace:
    """Use as a context manager:

        with Workspace(repo_root) as ws:
            ws.run("git", "diff")
            ...
            ws.merge_back(["target.py"])  # only if you want to keep something

    On exit, the worktree (and everything uncommitted inside it) is
    destroyed unconditionally - nothing survives unless merge_back() copied
    it out first. That's the automatic-rollback guarantee: a caller that
    forgets to call merge_back() on failure doesn't need to remember to
    clean up or revert anything.
    """

    def __init__(self, repo_root, base_ref="HEAD", timeout=DEFAULT_TIMEOUT_SECONDS,
                 memory_limit_mb=DEFAULT_MEMORY_LIMIT_MB):
        self.repo_root = repo_root
        self.base_ref = base_ref
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self.run_id = uuid.uuid4().hex[:12]
        self.path = os.path.join(_workspace_runs_dir(), self.run_id)

    def __enter__(self):
        os.makedirs(_workspace_runs_dir(), exist_ok=True)
        proc = subprocess.run(
            ["git", "worktree", "add", "--detach", self.path, self.base_ref],
            cwd=self.repo_root, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"could not create sandbox workspace: {proc.stderr.strip()}")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        proc = subprocess.run(
            ["git", "worktree", "remove", "--force", self.path],
            cwd=self.repo_root, capture_output=True, text=True,
        )
        if proc.returncode != 0 and os.path.isdir(self.path):
            # git refused (e.g. the path was already gone from under it) -
            # fall back to a plain removal so a workspace never lingers.
            shutil.rmtree(self.path, ignore_errors=True)
        return False

    def run(self, *args, timeout=None):
        """Run a fixed, caller-specified command inside the workspace.
        Returns (returncode, stdout, stderr); a timeout is reported as a
        non-zero return rather than raising, matching every other
        subprocess-wrapping function in this codebase (_git, test.run)."""
        try:
            proc = subprocess.run(
                args, cwd=self.path, capture_output=True, text=True,
                timeout=timeout if timeout is not None else self.timeout,
                preexec_fn=_memory_limit_preexec_fn(self.memory_limit_mb),
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 1, "", f"command timed out after {timeout or self.timeout}s"
        except (OSError, FileNotFoundError) as e:
            return 1, "", str(e)

    def merge_back(self, relative_paths, dest_root=None):
        """Copy specific files out of the workspace into the real repo -
        the only way anything here ever reaches the live checkout. Never
        called automatically."""
        dest_root = dest_root or self.repo_root
        copied = []
        for rel_path in relative_paths:
            src = os.path.join(self.path, rel_path)
            dest = os.path.join(dest_root, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(src, dest)
            copied.append(rel_path)
        return copied
