"""knowledge.write: save a file into the knowledge base, wrapped as a Tool.

RESTRICTED rather than SAFE - unlike search/fetch, this writes to disk.
Nothing enforces `permission` yet (that's Phase 15's job), but the
classification should be honest now so there's something real to enforce
later instead of everything defaulting to SAFE out of habit.
"""
from tools.base import Permission, Tool


class KnowledgeWriteTool(Tool):
    name = "knowledge.write"
    description = "Save content to a named file in the knowledge base."
    parameters = {"filename": "string", "content": "string"}
    permission = Permission.RESTRICTED

    def __init__(self, write_fn):
        self._write_fn = write_fn

    def execute(self, filename, content):
        return self._write_fn(filename, content)
