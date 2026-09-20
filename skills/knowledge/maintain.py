"""knowledge.maintain: inspect related knowledge and optionally forget one source."""
from skills.base import Skill
from tools.registry import registry as tool_registry


class KnowledgeMaintainSkill(Skill):
    name = "knowledge.maintain"
    description = "Find related saved knowledge and optionally archive-confirmed removal of one source."
    parameters = {"topic": "string", "forget_path": "string, optional", "confirm": "boolean, optional"}
    required_tools = ("knowledge.related", "knowledge.forget")

    def execute(self, topic, forget_path="", confirm=False):
        result = {"related": tool_registry.execute("knowledge.related", topic=topic)}
        if forget_path:
            result["forget"] = tool_registry.execute(
                "knowledge.forget", path=forget_path, confirm=confirm,
            )
        return result
