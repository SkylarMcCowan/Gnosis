"""research.verify: verify a draft against the evidence for the current request."""
from skills.base import Skill
from tools.registry import registry as tool_registry


class ResearchVerifySkill(Skill):
    name = "research.verify"
    description = "Verify a research draft against current-turn evidence and expose source-backed findings."
    parameters = {"answer_text": "string", "user_prompt": "string", "evidence": "list[object]"}
    required_tools = ("evidence.verify",)

    def execute(self, answer_text, user_prompt="", evidence=None):
        return tool_registry.execute(
            "evidence.verify", answer_text=answer_text,
            user_prompt=user_prompt, evidence=evidence or [],
        )
