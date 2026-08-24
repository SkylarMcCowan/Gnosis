"""execute_as_autonomous: the one real mechanism Phase 15 built - see
governance/__init__.py for the three explicit policy decisions this
implements. Wraps the real tools.registry.registry directly (not
injected) since this module's whole purpose is governing calls to that
one real, shared registry, the same way builder/validator.py imports
sandbox.workspace.Workspace directly rather than taking it as a parameter.
"""
from core.activity_log import record_activity
from tools.base import Permission
from tools.registry import registry as tool_registry

AUTONOMOUS_ACTION = "AUTONOMOUS_ACTION"


def execute_as_autonomous(name, agent=None, **kwargs):
    """Execute a tool on behalf of an autonomous caller - not a direct,
    human-typed command. Returns the tool's own result. Raises KeyError
    for an unknown tool name (matching ToolRegistry.execute's own
    behavior) and PermissionError for a FORBIDDEN one - a caller can't
    mistake either for a quiet success. Every allowed call is logged via
    core.activity_log's AUTONOMOUS_ACTION event, regardless of the tool's
    permission level, so there's always a real record of autonomous
    activity to review, not just the REQUIRES_APPROVAL ones."""
    tool = tool_registry.get(name)
    if tool is None:
        raise KeyError(f"No tool registered as {name!r}")
    if tool.permission == Permission.FORBIDDEN:
        record_activity(AUTONOMOUS_ACTION, tool=name, permission=tool.permission, allowed=False, agent=agent)
        raise PermissionError(f"'{name}' is FORBIDDEN - no autonomous caller may run it, regardless of policy.")
    result = tool_registry.execute(name, **kwargs)
    record_activity(AUTONOMOUS_ACTION, tool=name, permission=tool.permission, allowed=True, agent=agent)
    return result
