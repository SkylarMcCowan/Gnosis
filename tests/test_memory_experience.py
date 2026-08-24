"""Regression tests for memory/experience.py, the Phase 5 Experience
System - build_experience/score_experience/extract_lessons (pure,
deterministic) and record_experience/load_experiences/experience_to_knowledge
(the disk-touching side, always run under isolated_data_dir).
"""
from memory.experience import (
    build_experience, experience_to_knowledge, extract_lessons,
    load_experiences, record_experience, score_experience,
)
from tools.registry import registry as tool_registry


def test_score_experience_is_binary_on_success():
    assert score_experience(True) == 1.0
    assert score_experience(False) == 0.0
    assert score_experience(None) == 0.0


def test_extract_lessons_for_a_success():
    experience = {"goal": "fix the bug", "success": True, "result": "all good"}
    assert extract_lessons(experience) == ["Succeeded: fix the bug."]


def test_extract_lessons_for_a_failure_includes_a_result_snippet():
    experience = {"goal": "fix the bug", "success": False, "result": "tests failed: assertion error"}
    lessons = extract_lessons(experience)
    assert len(lessons) == 1
    assert lessons[0].startswith("Failed: fix the bug (tests failed: assertion error")


def test_extract_lessons_for_not_attempted():
    experience = {"goal": "fix the bug", "success": None, "result": ""}
    assert extract_lessons(experience) == ["Not attempted: fix the bug."]


def test_build_experience_fills_in_defaults():
    experience = build_experience(goal="research a topic", success=True)
    assert experience["goal"] == "research a topic"
    assert experience["plan"] == ""
    assert experience["actions"] == []
    assert experience["tools_used"] == []
    assert experience["success"] is True
    assert experience["score"] == 1.0
    assert experience["lessons"] == ["Succeeded: research a topic."]
    assert experience["agent"] is None
    assert experience["skill"] is None
    assert "timestamp" in experience


def test_build_experience_honors_explicit_score_and_lessons():
    experience = build_experience(
        goal="g", success=True, score=0.42, lessons=["a custom lesson"],
    )
    assert experience["score"] == 0.42
    assert experience["lessons"] == ["a custom lesson"]


def test_record_and_load_experiences_round_trip(isolated_data_dir):
    record_experience(build_experience(goal="first", success=True, skill="research.topic"))
    record_experience(build_experience(goal="second", success=False, skill="research.topic"))
    record_experience(build_experience(goal="third", success=True, skill=None))

    all_experiences = load_experiences()
    assert [e["goal"] for e in all_experiences] == ["first", "second", "third"]


def test_load_experiences_filters_by_skill(isolated_data_dir):
    record_experience(build_experience(goal="first", success=True, skill="research.topic"))
    record_experience(build_experience(goal="second", success=True, skill="other.skill"))

    filtered = load_experiences(skill="research.topic")
    assert [e["goal"] for e in filtered] == ["first"]


def test_load_experiences_filters_by_success(isolated_data_dir):
    record_experience(build_experience(goal="first", success=True))
    record_experience(build_experience(goal="second", success=False))

    assert [e["goal"] for e in load_experiences(success=True)] == ["first"]
    assert [e["goal"] for e in load_experiences(success=False)] == ["second"]


def test_load_experiences_respects_limit(isolated_data_dir):
    for i in range(5):
        record_experience(build_experience(goal=f"goal {i}", success=True))

    assert [e["goal"] for e in load_experiences(limit=2)] == ["goal 3", "goal 4"]


def test_load_experiences_returns_empty_list_when_no_log_exists(isolated_data_dir):
    assert load_experiences() == []


def test_experience_to_knowledge_writes_a_real_summary(isolated_data_dir):
    experience = build_experience(
        goal="fix the bug", success=True, tools_used=["repo.audit", "test.run"],
        result="applied",
    )

    filename = experience_to_knowledge(experience)

    found = tool_registry.execute("knowledge.search", topic="fix the bug")
    assert any(name == filename for name, _ in found)
    content = dict(found)[filename]
    assert "Goal: fix the bug" in content
    assert "Tools used: repo.audit, test.run" in content
    assert "Succeeded: fix the bug." in content
