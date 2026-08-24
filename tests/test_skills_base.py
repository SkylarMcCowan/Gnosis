"""Regression tests for skills/base.py's Skill ABC, in particular
resolved_permission()'s "can't be safer than the riskiest tool it calls"
rule.
"""
from tools.base import Permission, Tool
from tools.registry import ToolRegistry
import skills.base as skills_base
from skills.base import Skill


class _FakeTool(Tool):
    def __init__(self, name, permission):
        self.name = name
        self.permission = permission

    def execute(self, **kwargs):
        return kwargs


class _FakeSkill(Skill):
    name = "test.skill"
    required_tools = ("a.tool", "b.tool")

    def execute(self, **kwargs):
        return kwargs


def _patched_registry(monkeypatch, tools):
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)
    monkeypatch.setattr(skills_base, "tool_registry", reg)
    return reg


def test_resolved_permission_defaults_to_safe_with_no_required_tools():
    class NoDeps(Skill):
        name = "test.no_deps"

        def execute(self, **kwargs):
            return kwargs

    assert NoDeps().resolved_permission() == Permission.SAFE


def test_resolved_permission_takes_the_strictest_required_tool(monkeypatch):
    _patched_registry(monkeypatch, [
        _FakeTool("a.tool", Permission.SAFE),
        _FakeTool("b.tool", Permission.REQUIRES_APPROVAL),
    ])
    assert _FakeSkill().resolved_permission() == Permission.REQUIRES_APPROVAL


def test_resolved_permission_ignores_a_required_tool_that_is_not_registered(monkeypatch):
    _patched_registry(monkeypatch, [_FakeTool("a.tool", Permission.RESTRICTED)])
    assert _FakeSkill().resolved_permission() == Permission.RESTRICTED


def test_explicit_permission_overrides_derivation(monkeypatch):
    _patched_registry(monkeypatch, [
        _FakeTool("a.tool", Permission.SAFE),
        _FakeTool("b.tool", Permission.SAFE),
    ])

    class Explicit(_FakeSkill):
        permission = Permission.FORBIDDEN

    assert Explicit().resolved_permission() == Permission.FORBIDDEN
