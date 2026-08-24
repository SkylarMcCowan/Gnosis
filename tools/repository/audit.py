"""repo.audit: a text summary of the repo (file/line counts, TODOs, large
files, whether a tests folder exists), wrapped as a Tool.
"""
from tools.base import Permission, Tool


class RepoAuditTool(Tool):
    name = "repo.audit"
    description = "Summarize the repository: file/line counts, TODO/FIXME findings, large files, tests folder presence."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, audit_fn):
        self._audit_fn = audit_fn

    def execute(self):
        return self._audit_fn()
