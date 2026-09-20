"""model.status: bounded local model and session status."""
from tools.base import Permission, Tool


class ModelStatusTool(Tool):
    name = "model.status"
    description = "Report selected model, availability, context budget, active modes, and recent metrics."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, status_fn):
        self._status_fn = status_fn

    def execute(self):
        return self._status_fn()
