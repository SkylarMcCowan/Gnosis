"""web.search: the first real capability wrapped as a Tool (Phase 2 pilot).

Constructed with the underlying search callable injected, exactly like
core/command_router.py's handlers - this module never imports webagent.py,
so webagent.py is what instantiates and registers this with the shared
tools.registry.registry, binding it to its own search_web().
"""
from tools.base import Permission, Tool


class WebSearchTool(Tool):
    name = "web.search"
    description = "Search the web for a query and return ranked results."
    parameters = {"query": "string"}
    permission = Permission.SAFE

    def __init__(self, search_fn):
        self._search_fn = search_fn

    def execute(self, query):
        return self._search_fn(query)
