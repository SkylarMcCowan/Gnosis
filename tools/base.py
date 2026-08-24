"""The Tool interface: one capability, named, described, and invoked the
same way regardless of what actually implements it underneath.

This is the "sacred principle" from the roadmap made concrete: Gnosis should
know it has a capability called `web.search`, not that `web.search` happens
to call a particular function in webagent.py using a particular search
engine. A Tool wraps that function (or class, or subprocess call, or
anything else) behind a fixed name/description/parameter shape, so the
*caller* never needs to change when the implementation does.

Tools are deliberately dumb about *how* their underlying capability works -
each one is constructed with whatever callable actually does the work
(dependency injection), so this module never imports webagent.py or
anything else Gnosis-specific. That keeps this package usable from
anywhere, and avoids the circular import a direct `import webagent` would
create.

HOW TO ADD A NEW TOOL (the pattern every tool in this package follows -
see tools/web/search.py for the first real one):

1. Pick a dotted name in the category it belongs to - `web.search`,
   `fs.read`, `cron.add` - matching the tools/<category>/ subpackage it
   lives in (tools/web/, tools/filesystem/, tools/shell/, tools/scheduler/,
   tools/knowledge/, tools/communication/; add a new subpackage if a
   capability doesn't fit any existing one).
2. Create tools/<category>/<thing>.py with a Tool subclass:

       from tools.base import Permission, Tool

       class MyTool(Tool):
           name = "category.thing"
           description = "One sentence a planner or a human could act on."
           parameters = {"arg_name": "string"}
           permission = Permission.SAFE  # RESTRICTED/REQUIRES_APPROVAL/FORBIDDEN for anything riskier

           def __init__(self, do_the_thing):
               self._do_the_thing = do_the_thing  # the real implementation, injected

           def execute(self, arg_name):
               return self._do_the_thing(arg_name)

3. In webagent.py's `_register_tools()`, construct it with the real
   function and register it: `tool_registry.register(MyTool(real_function))`.
4. Write two kinds of test: one for the Tool class in isolation (construct
   it with a fake callable, assert execute() forwards correctly - see
   tests/test_tools_web_search.py), and one proving webagent.py actually
   registered it bound to the real implementation (see
   tests/test_tools_wiring.py's pattern: mock the real function's own
   dependency, call `tool_registry.execute(name, ...)`, and check the
   result came from the real code path, not a stand-in).

Nothing internal has to call through the registry for a tool to be worth
adding - Phase 2 explicitly allows tools to exist and be correct before
anything depends on them (migrating internal callers is tracked separately
in TODO.md). Registering a capability here is what makes it something a
future planner, skill, or Gnosis itself can discover and invoke by name
instead of needing to know it lives in webagent.py at all.
"""
from abc import ABC, abstractmethod


class Permission:
    SAFE = "SAFE"
    RESTRICTED = "RESTRICTED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    FORBIDDEN = "FORBIDDEN"


class Tool(ABC):
    """Subclass this and set name/description/parameters/permission, then
    implement execute(). parameters is a plain dict describing the shape of
    the keyword arguments execute() accepts - documentation for now (Phase
    2's ToolRegistry doesn't validate against it yet), not a JSON Schema
    validator."""

    name = None
    description = None
    parameters = {}
    permission = Permission.SAFE

    @abstractmethod
    def execute(self, **kwargs):
        raise NotImplementedError
