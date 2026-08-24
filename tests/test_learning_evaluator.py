"""Regression tests for learning/evaluator.py, Phase 6's Learning Engine
evaluator - operates purely on memory.experience's recorded dicts.
"""
from learning.evaluator import evaluate_recent_performance
from memory.experience import build_experience, record_experience


def _record(goal, success, agent=None, skill=None):
    record_experience(build_experience(goal=goal, success=success, agent=agent, skill=skill))


def test_evaluate_recent_performance_with_no_experiences_returns_none_rate(isolated_data_dir):
    result = evaluate_recent_performance()
    assert result == {"total": 0, "attempted": 0, "succeeded": 0, "not_attempted": 0, "success_rate": None}


def test_evaluate_recent_performance_computes_success_rate(isolated_data_dir):
    _record("a", True)
    _record("b", False)
    _record("c", True)

    result = evaluate_recent_performance()

    assert result["total"] == 3
    assert result["attempted"] == 3
    assert result["succeeded"] == 2
    assert result["success_rate"] == 2 / 3


def test_evaluate_recent_performance_excludes_not_attempted_from_rate(isolated_data_dir):
    _record("blocked", None)
    _record("blocked again", None)
    _record("applied", True)

    result = evaluate_recent_performance()

    assert result["total"] == 3
    assert result["not_attempted"] == 2
    assert result["attempted"] == 1
    assert result["success_rate"] == 1.0


def test_evaluate_recent_performance_filters_by_agent(isolated_data_dir):
    _record("a", True, agent="self-improve")
    _record("b", False, agent="other-agent")

    result = evaluate_recent_performance(agent="self-improve")

    assert result["total"] == 1
    assert result["success_rate"] == 1.0


def test_evaluate_recent_performance_respects_window(isolated_data_dir):
    for i in range(5):
        _record(f"goal {i}", False)
    _record("goal 5", True)

    result = evaluate_recent_performance(window=1)

    assert result["total"] == 1
    assert result["success_rate"] == 1.0
