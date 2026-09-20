"""conversation.recover: inspect the active topic and optionally plan next steps."""
from skills.base import Skill
from tools.registry import registry as tool_registry


class ConversationRecoverSkill(Skill):
    name = "conversation.recover"
    description = "Recover the active topic and produce a bounded next-step plan when needed."
    parameters = {"goal": "string, optional"}
    required_tools = ("conversation.inspect", "task.plan")

    def execute(self, goal=""):
        inspection = tool_registry.execute("conversation.inspect")
        plan = tool_registry.execute("task.plan", goal=goal, context=str(inspection)) if goal else None
        return {"conversation": inspection, "plan": plan}
