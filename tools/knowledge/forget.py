"""knowledge.forget: explicitly confirmed, archive-first knowledge removal."""
from tools.base import Permission, Tool


class KnowledgeForgetTool(Tool):
    name = "knowledge.forget"
    description = "Archive and remove a selected saved knowledge source after explicit confirmation."
    parameters = {"path": "string", "confirm": "boolean"}
    permission = Permission.REQUIRES_APPROVAL

    def __init__(self, forget_fn):
        self._forget_fn = forget_fn

    def execute(self, path, confirm=False):
        return self._forget_fn(path, confirm=confirm)
