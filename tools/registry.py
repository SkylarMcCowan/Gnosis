"""ToolRegistry: where Gnosis looks up "do I have a capability called X" and
invokes it, instead of importing whatever module happens to implement X.

Enforces two things that only matter once many tools exist, but are cheap to
guarantee from day one: every registered tool has a real name, and two
different tools can never silently clobber each other under the same name.
Both would otherwise be invisible bugs - a Tool subclass that forgets to set
`name` defaults to `None` and would register fine with nothing to catch it;
two tools sharing a name (a real risk once Phase 9's self-generated tools
start registering things nobody hand-reviewed line by line) would silently
overwrite one another with no error, just a capability quietly vanishing.
"""


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool, replace=False):
        """Register a tool. Raises ValueError if it has no name, or if a
        *different* tool is already registered under that name and
        replace=False. Re-registering the exact same object (e.g. a module
        reloaded in a test) is always allowed."""
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} must set a non-empty `name` before it can be registered")
        existing = self._tools.get(tool.name)
        if existing is not None and existing is not tool and not replace:
            raise ValueError(
                f"A different tool is already registered as {tool.name!r} "
                f"({type(existing).__name__}) - pass replace=True if this is intentional"
            )
        self._tools[tool.name] = tool

    def unregister(self, name):
        self._tools.pop(name, None)

    def get(self, name):
        return self._tools.get(name)

    def list(self):
        return list(self._tools.values())

    def list_namespace(self, prefix):
        """Every tool whose name starts with `prefix.` - e.g. list_namespace("web")
        returns web.search, web.fetch, etc. The namespace convention (a dot
        after the category) is what tools/<category>/ directories exist for."""
        dotted = f"{prefix}."
        return [tool for tool in self._tools.values() if tool.name.startswith(dotted)]

    def search(self, query):
        """Case-insensitive substring match against each tool's name and
        description - a placeholder for real semantic search later."""
        query = query.lower()
        return [
            tool for tool in self._tools.values()
            if query in tool.name.lower() or query in (tool.description or "").lower()
        ]

    def execute(self, name, **kwargs):
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"No tool registered as {name!r}")
        return tool.execute(**kwargs)


registry = ToolRegistry()
