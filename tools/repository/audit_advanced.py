"""repo.audit_advanced: a higher-level repo health pass, wrapped as a Tool
- README quality, test-suite presence, CI config detection, docs health.
Complements repo.audit (file/line/TODO/size stats), doesn't replace it.
"""
from tools.base import Permission, Tool


class RepoAuditAdvancedTool(Tool):
    name = "repo.audit_advanced"
    description = "Assess README quality, test-suite presence, CI config, and docs health for the repository."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, audit_fn):
        self._audit_fn = audit_fn

    def execute(self):
        return self._audit_fn()
