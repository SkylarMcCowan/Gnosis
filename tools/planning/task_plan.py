"""task.plan: bounded planning without persistence or execution."""
from tools.base import Permission, Tool


class TaskPlanTool(Tool):
    name = "task.plan"
    description = "Turn a goal into a bounded checklist with dependencies and a next action."
    parameters = {"goal": "string", "context": "string, optional"}
    permission = Permission.SAFE

    def __init__(self, plan_fn):
        self._plan_fn = plan_fn

    def execute(self, goal, context=""):
        return self._plan_fn(goal, context=context)
