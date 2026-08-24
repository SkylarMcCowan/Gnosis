"""knowledge.search: search the knowledge base for a topic, wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class KnowledgeSearchTool(Tool):
    name = "knowledge.search"
    description = "Search the knowledge base for a topic and return matching (filename, content) pairs."
    parameters = {"topic": "string"}
    permission = Permission.SAFE

    def __init__(self, search_fn):
        self._search_fn = search_fn

    def execute(self, topic):
        return self._search_fn(topic)
