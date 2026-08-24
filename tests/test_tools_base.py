"""Regression tests for tools/base.py, the Tool interface behind Phase 2."""
import pytest

from tools.base import Permission, Tool


def test_tool_is_abstract_without_execute():
    class Incomplete(Tool):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()


def test_concrete_tool_can_be_constructed_and_executed():
    class Echo(Tool):
        name = "echo"
        description = "Return whatever it's given."
        parameters = {"value": "any"}
        permission = Permission.SAFE

        def execute(self, value):
            return value

    tool = Echo()
    assert tool.execute(value=42) == 42
    assert tool.name == "echo"
    assert tool.permission == Permission.SAFE
