"""The Skill interface: a named, described composition of one or more
registered Tools - e.g. `web.search -> web.fetch -> knowledge.search ->
knowledge.write` becomes the `research.topic` skill, exactly as this
roadmap's own Phase 3 sketch names it.

A Skill never imports webagent.py or calls its functions directly - it only
ever reaches a capability through `tools.registry.registry.execute(name,
...)`, the same seam Phase 2 built for internal webagent.py callers. A
skill is nothing more than "a caller that happens to be reusable, named,
and discoverable" - this module never needs to change when what's under
`web.search` changes, for the same reason Tool didn't.

HOW TO ADD A NEW SKILL (mirrors tools/base.py's "HOW TO ADD A NEW TOOL"):

1. Pick a dotted name in the category it belongs to - `research.topic`,
   `coding.review` - matching the skills/<category>/ subpackage it lives in
   (skills/research/, skills/coding/, skills/documentation/,
   skills/system_management/; add a new subpackage if it doesn't fit).
2. Create skills/<category>/<thing>.py with a Skill subclass:

       from tools.registry import registry as tool_registry
       from skills.base import Skill

       class MyTopicSkill(Skill):
           name = "category.thing"
           description = "One sentence a planner or a human could act on."
           parameters = {"arg_name": "string"}
           required_tools = ("web.search", "knowledge.write")

           def execute(self, arg_name):
               results = tool_registry.execute("web.search", query=arg_name)
               ...
               return results

3. Leave `permission` unset unless the skill needs to be *more* restrictive
   than the riskiest tool it calls - `resolved_permission()` already
   derives that floor from `required_tools` automatically.
4. In webagent.py's `_register_skills()`, register it:
   `skill_registry.register(MyTopicSkill())`. Unlike Tool, a Skill isn't
   constructed with an injected function - it composes already-registered
   tools by name, so there's nothing to inject.
5. Write two kinds of test: one for the Skill class in isolation (a fake
   tool_registry.execute swapped in via monkeypatch, assert it calls the
   right tools in the right order with the right args), and one wiring test
   proving `skill_registry.execute(name, ...)` reaches the real tools (see
   tests/test_skills_wiring.py's pattern).
"""
from abc import ABC, abstractmethod

from tools.base import Permission
from tools.registry import registry as tool_registry

_PERMISSION_ORDER = [Permission.SAFE, Permission.RESTRICTED, Permission.REQUIRES_APPROVAL, Permission.FORBIDDEN]


class Skill(ABC):
    """Subclass this and set name/description/parameters/required_tools,
    then implement execute(). `parameters` is documentation only, same as
    Tool's - not validated against yet."""

    name = None
    description = None
    parameters = {}
    required_tools = ()
    permission = None  # None => derive from required_tools; see resolved_permission()

    @abstractmethod
    def execute(self, **kwargs):
        raise NotImplementedError

    def resolved_permission(self):
        """This skill's own `permission` if set; otherwise the strictest
        permission among its required_tools - a skill can't be safer than
        the riskiest tool it calls, even if every individual call site looks
        harmless in isolation."""
        if self.permission is not None:
            return self.permission
        strictest = Permission.SAFE
        for tool_name in self.required_tools:
            tool = tool_registry.get(tool_name)
            if tool is not None and _PERMISSION_ORDER.index(tool.permission) > _PERMISSION_ORDER.index(strictest):
                strictest = tool.permission
        return strictest
