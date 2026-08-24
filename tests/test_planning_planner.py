"""Regression tests for planning/planner.py, Phase 7's one real decision
point - is_stuck_goal, built directly on Phase 6's critic.
"""
from planning.planner import is_stuck_goal
from memory.experience import build_experience, record_experience


def _record(goal, success, agent=None):
    record_experience(build_experience(goal=goal, success=success, agent=agent))


def test_is_stuck_goal_false_with_no_history(isolated_data_dir):
    assert is_stuck_goal("fix target.py: bug") is False


def test_is_stuck_goal_false_after_a_single_failure(isolated_data_dir):
    _record("fix target.py: bug", False)
    assert is_stuck_goal("fix target.py: bug") is False


def test_is_stuck_goal_true_after_repeated_failures(isolated_data_dir):
    _record("fix target.py: bug", False)
    _record("fix target.py: bug", False)
    assert is_stuck_goal("fix target.py: bug") is True


def test_is_stuck_goal_false_for_a_different_goal(isolated_data_dir):
    _record("fix target.py: bug", False)
    _record("fix target.py: bug", False)
    assert is_stuck_goal("fix other.py: different bug") is False


def test_is_stuck_goal_filters_by_agent(isolated_data_dir):
    _record("fix target.py: bug", False, agent="self-improve")
    _record("fix target.py: bug", False, agent="self-improve")
    assert is_stuck_goal("fix target.py: bug", agent="other-agent") is False
    assert is_stuck_goal("fix target.py: bug", agent="self-improve") is True


def test_is_stuck_goal_respects_a_custom_min_pattern_count(isolated_data_dir):
    _record("fix target.py: bug", False)
    _record("fix target.py: bug", False)
    assert is_stuck_goal("fix target.py: bug", min_pattern_count=3) is False
