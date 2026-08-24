"""Regression tests for skills/registry.py, the SkillRegistry behind Phase 3.

Dependency validation (register() checking required_tools) is tested
against the real tools.registry.registry rather than a fake one, since
SkillRegistry always imports the real shared registry - "web.search" is
used as a stand-in for "a tool that really is registered" (webagent.py
registers it at import time, which conftest.py triggers for every test)
and "nonexistent.tool" for "a tool that really isn't".
"""
import pytest

import webagent  # noqa: F401  (ensures the real tools are registered before these tests run)
from skills.base import Skill
from skills.registry import SkillRegistry


class _FakeSkill(Skill):
    def __init__(self, name, description="", required_tools=(), calls=None):
        self.name = name
        self.description = description
        self.required_tools = required_tools
        self._calls = calls if calls is not None else []

    def execute(self, **kwargs):
        self._calls.append(kwargs)
        return kwargs


def test_register_and_get():
    reg = SkillRegistry()
    skill = _FakeSkill("research.topic")
    reg.register(skill)
    assert reg.get("research.topic") is skill


def test_get_unknown_returns_none():
    reg = SkillRegistry()
    assert reg.get("nope") is None


def test_unregister_removes_the_skill():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    reg.unregister("research.topic")
    assert reg.get("research.topic") is None


def test_unregister_unknown_is_a_noop():
    reg = SkillRegistry()
    reg.unregister("never_registered")  # must not raise


def test_list_returns_every_registered_skill():
    reg = SkillRegistry()
    a, b = _FakeSkill("a"), _FakeSkill("b")
    reg.register(a)
    reg.register(b)
    assert set(reg.list()) == {a, b}


def test_search_matches_name_or_description_case_insensitively():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic", description="Research a topic"))
    reg.register(_FakeSkill("coding.review", description="Review a diff"))

    assert [s.name for s in reg.search("RESEARCH")] == ["research.topic"]
    assert [s.name for s in reg.search("diff")] == ["coding.review"]
    assert reg.search("nonexistent") == []


def test_execute_calls_the_skill_with_kwargs():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    assert reg.execute("research.topic", topic="astronomy") == {"topic": "astronomy"}


def test_execute_unknown_skill_raises_keyerror():
    reg = SkillRegistry()
    with pytest.raises(KeyError):
        reg.execute("nope")


def test_register_rejects_a_skill_with_no_name():
    reg = SkillRegistry()
    with pytest.raises(ValueError, match="name"):
        reg.register(_FakeSkill(name=None))


def test_register_rejects_a_different_skill_reusing_an_existing_name():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    with pytest.raises(ValueError, match="research.topic"):
        reg.register(_FakeSkill("research.topic"))
    assert reg.get("research.topic") is not None


def test_register_replace_true_allows_overwriting():
    reg = SkillRegistry()
    original = _FakeSkill("research.topic")
    replacement = _FakeSkill("research.topic")
    reg.register(original)
    reg.register(replacement, replace=True)
    assert reg.get("research.topic") is replacement


def test_register_the_same_object_twice_is_not_an_error():
    reg = SkillRegistry()
    skill = _FakeSkill("research.topic")
    reg.register(skill)
    reg.register(skill)
    assert reg.get("research.topic") is skill


def test_list_namespace_returns_only_skills_in_that_category():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    reg.register(_FakeSkill("research.summarize"))
    reg.register(_FakeSkill("coding.review"))

    names = sorted(s.name for s in reg.list_namespace("research"))
    assert names == ["research.summarize", "research.topic"]


def test_list_namespace_does_not_match_an_unrelated_prefix():
    reg = SkillRegistry()
    reg.register(_FakeSkill("researchers.notify"))
    assert reg.list_namespace("research") == []


def test_register_rejects_a_skill_requiring_an_unregistered_tool():
    reg = SkillRegistry()
    with pytest.raises(ValueError, match="nonexistent.tool"):
        reg.register(_FakeSkill("research.topic", required_tools=("nonexistent.tool",)))


def test_register_accepts_a_skill_requiring_a_real_registered_tool():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic", required_tools=("web.search",)))
    assert reg.get("research.topic") is not None


def test_disable_prevents_execute():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    reg.disable("research.topic")
    with pytest.raises(RuntimeError, match="disabled"):
        reg.execute("research.topic", topic="x")


def test_enable_reverses_disable():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    reg.disable("research.topic")
    reg.enable("research.topic")
    assert reg.execute("research.topic", topic="x") == {"topic": "x"}


def test_disable_unknown_skill_raises_keyerror():
    reg = SkillRegistry()
    with pytest.raises(KeyError):
        reg.disable("nope")


def test_is_enabled_reflects_registration_and_disable_state():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    assert reg.is_enabled("research.topic") is True
    reg.disable("research.topic")
    assert reg.is_enabled("research.topic") is False
    assert reg.is_enabled("never_registered") is False


def test_unregister_also_clears_disabled_state():
    reg = SkillRegistry()
    reg.register(_FakeSkill("research.topic"))
    reg.disable("research.topic")
    reg.unregister("research.topic")
    reg.register(_FakeSkill("research.topic"))
    assert reg.is_enabled("research.topic") is True
