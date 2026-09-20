"""knowledge.related: provenance-aware related knowledge lookup."""
from tools.base import Permission, Tool


class KnowledgeRelatedTool(Tool):
    name = "knowledge.related"
    description = "Find related saved knowledge with source provenance and retrieval signals."
    parameters = {"topic": "string", "limit": "integer, optional"}
    permission = Permission.SAFE

    def __init__(self, related_fn):
        self._related_fn = related_fn

    def execute(self, topic, limit=5):
        return self._related_fn(topic, limit=limit)
