"""Regression tests for learning/reflection.py, Phase 6's lesson
consolidation over recorded Experiences.
"""
from learning.reflection import consolidated_lessons
from memory.experience import build_experience, record_experience


def _record(goal, success, agent=None, skill=None):
    record_experience(build_experience(goal=goal, success=success, agent=agent, skill=skill))


def test_consolidated_lessons_empty_with_no_experiences(isolated_data_dir):
    assert consolidated_lessons() == []


def test_consolidated_lessons_counts_and_ranks(isolated_data_dir):
    _record("fix a", False)  # lesson: "Failed: fix a."
    _record("fix a", False)
    _record("fix b", True)  # lesson: "Succeeded: fix b."

    result = consolidated_lessons()

    assert result[0] == ("Failed: fix a.", 2)
    assert ("Succeeded: fix b.", 1) in result


def test_consolidated_lessons_respects_window(isolated_data_dir):
    for _ in range(5):
        _record("old failure", False)
    _record("recent success", True)

    result = consolidated_lessons(window=1)

    assert result == [("Succeeded: recent success.", 1)]


def test_consolidated_lessons_filters_by_agent(isolated_data_dir):
    _record("fix a", False, agent="self-improve")
    _record("fix a", False, agent="other-agent")

    result = consolidated_lessons(agent="self-improve")

    assert result == [("Failed: fix a.", 1)]
