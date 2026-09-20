"""conversation.inspect: bounded, read-only conversation diagnostics."""
import re

from tools.base import Permission, Tool


class ConversationInspectTool(Tool):
    name = "conversation.inspect"
    description = (
        "Inspect the active conversation topic, recent user turns, follow-up status, "
        "and requested output constraints without exposing the full transcript."
    )
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, inspect_fn):
        self._inspect_fn = inspect_fn

    def execute(self):
        return self._inspect_fn()
