"""Regression tests for tools/registry.py, the ToolRegistry behind Phase 2."""
import pytest

from tools.base import Tool
from tools.registry import ToolRegistry


class _FakeTool(Tool):
    def __init__(self, name, description="", calls=None):
        self.name = name
        self.description = description
        self._calls = calls if calls is not None else []

    def execute(self, **kwargs):
        self._calls.append(kwargs)
        return kwargs


def test_register_and_get():
    reg = ToolRegistry()
    tool = _FakeTool("web.search")
    reg.register(tool)
    assert reg.get("web.search") is tool


def test_get_unknown_returns_none():
    reg = ToolRegistry()
    assert reg.get("nope") is None


def test_unregister_removes_the_tool():
    reg = ToolRegistry()
    reg.register(_FakeTool("web.search"))
    reg.unregister("web.search")
    assert reg.get("web.search") is None


def test_unregister_unknown_is_a_noop():
    reg = ToolRegistry()
    reg.unregister("never_registered")  # must not raise


def test_list_returns_every_registered_tool():
    reg = ToolRegistry()
    a, b = _FakeTool("a"), _FakeTool("b")
    reg.register(a)
    reg.register(b)
    assert set(reg.list()) == {a, b}


def test_search_matches_name_or_description_case_insensitively():
    reg = ToolRegistry()
    reg.register(_FakeTool("web.search", description="Search the web"))
    reg.register(_FakeTool("fs.read", description="Read a file"))

    assert [t.name for t in reg.search("WEB")] == ["web.search"]
    assert [t.name for t in reg.search("file")] == ["fs.read"]
    assert reg.search("nonexistent") == []


def test_execute_calls_the_tool_with_kwargs():
    reg = ToolRegistry()
    reg.register(_FakeTool("web.search"))
    assert reg.execute("web.search", query="astronomy") == {"query": "astronomy"}


def test_execute_unknown_tool_raises_keyerror():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.execute("nope")


def test_register_rejects_a_tool_with_no_name():
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="name"):
        reg.register(_FakeTool(name=None))


def test_register_rejects_a_different_tool_reusing_an_existing_name():
    reg = ToolRegistry()
    reg.register(_FakeTool("web.search"))
    with pytest.raises(ValueError, match="web.search"):
        reg.register(_FakeTool("web.search"))
    # the original registration must survive the rejected attempt
    assert reg.get("web.search") is not None


def test_register_replace_true_allows_overwriting():
    reg = ToolRegistry()
    original = _FakeTool("web.search")
    replacement = _FakeTool("web.search")
    reg.register(original)
    reg.register(replacement, replace=True)
    assert reg.get("web.search") is replacement


def test_register_the_same_object_twice_is_not_an_error():
    reg = ToolRegistry()
    tool = _FakeTool("web.search")
    reg.register(tool)
    reg.register(tool)  # re-registering the identical object, e.g. a reloaded module
    assert reg.get("web.search") is tool


def test_list_namespace_returns_only_tools_in_that_category():
    reg = ToolRegistry()
    reg.register(_FakeTool("web.search"))
    reg.register(_FakeTool("web.fetch"))
    reg.register(_FakeTool("fs.read"))

    names = sorted(t.name for t in reg.list_namespace("web"))
    assert names == ["web.fetch", "web.search"]


def test_list_namespace_does_not_match_an_unrelated_prefix():
    """"web" must not match a hypothetical "webhook.send" - the dot after
    the category is what makes this a namespace, not just a prefix."""
    reg = ToolRegistry()
    reg.register(_FakeTool("webhook.send"))
    assert reg.list_namespace("web") == []
