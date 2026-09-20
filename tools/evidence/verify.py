"""evidence.verify: structured access to the existing fact-checking pass."""
from tools.base import Permission, Tool


class EvidenceVerifyTool(Tool):
    name = "evidence.verify"
    description = (
        "Check a drafted answer against current-turn evidence and report supported, "
        "unsupported, conflicting, or wrong-entity claims."
    )
    parameters = {
        "answer_text": "string",
        "user_prompt": "string",
        "evidence": "list[object]",
    }
    permission = Permission.SAFE

    def __init__(self, verify_fn):
        self._verify_fn = verify_fn

    def execute(self, answer_text, user_prompt="", evidence=None):
        return self._verify_fn(answer_text, evidence or [], user_prompt=user_prompt)
