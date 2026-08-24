"""SkillRegistry: the same name/collision validation and register/get/
list/list_namespace/search/execute shape as tools.registry.ToolRegistry,
plus two things a Tool doesn't need: dependency validation (a skill that
requires a tool which isn't registered fails loudly at registration time,
not silently at first use) and enable/disable (a skill can be turned off
without unregistering it, so a bad or in-progress skill doesn't have to be
pulled out of the registry entirely to stop it from running).

Kept as its own instance rather than sharing tools.registry.registry's
dict, so "list every skill" and "list every tool" stay separate questions -
skills and tools are discoverable independently even though a skill's
`required_tools` links the two.
"""
from tools.registry import registry as tool_registry


class SkillRegistry:
    def __init__(self):
        self._skills = {}
        self._disabled = set()

    def register(self, skill, replace=False):
        """Register a skill. Raises ValueError if it has no name, if a
        *different* skill is already registered under that name and
        replace=False, or if any of its required_tools isn't registered in
        tools.registry.registry. Re-registering the exact same object is
        always allowed."""
        if not skill.name:
            raise ValueError(f"{type(skill).__name__} must set a non-empty `name` before it can be registered")
        missing = [t for t in skill.required_tools if tool_registry.get(t) is None]
        if missing:
            raise ValueError(f"Skill {skill.name!r} requires tool(s) {missing!r} which aren't registered")
        existing = self._skills.get(skill.name)
        if existing is not None and existing is not skill and not replace:
            raise ValueError(
                f"A different skill is already registered as {skill.name!r} "
                f"({type(existing).__name__}) - pass replace=True if this is intentional"
            )
        self._skills[skill.name] = skill

    def unregister(self, name):
        self._skills.pop(name, None)
        self._disabled.discard(name)

    def get(self, name):
        return self._skills.get(name)

    def list(self):
        return list(self._skills.values())

    def list_namespace(self, prefix):
        """Every skill whose name starts with `prefix.` - e.g.
        list_namespace("research") returns research.topic, etc."""
        dotted = f"{prefix}."
        return [skill for skill in self._skills.values() if skill.name.startswith(dotted)]

    def search(self, query):
        """Case-insensitive substring match against each skill's name and
        description - a placeholder for real semantic search later."""
        query = query.lower()
        return [
            skill for skill in self._skills.values()
            if query in skill.name.lower() or query in (skill.description or "").lower()
        ]

    def disable(self, name):
        if name not in self._skills:
            raise KeyError(f"No skill registered as {name!r}")
        self._disabled.add(name)

    def enable(self, name):
        self._disabled.discard(name)

    def is_enabled(self, name):
        return name in self._skills and name not in self._disabled

    def execute(self, name, **kwargs):
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"No skill registered as {name!r}")
        if name in self._disabled:
            raise RuntimeError(f"Skill {name!r} is disabled")
        return skill.execute(**kwargs)


registry = SkillRegistry()
