"""Regression tests for learning/critic.py, Phase 6's rule-based
failure-pattern detector - deterministic, no model call.
"""
from learning.critic import critique_recent_failures
from memory.experience import build_experience, record_experience


def _record(goal, success, tools_used=None, agent=None):
    record_experience(build_experience(goal=goal, success=success, tools_used=tools_used, agent=agent))


def test_critique_returns_empty_with_no_failures(isolated_data_dir):
    _record("a", True)
    assert critique_recent_failures() == []


def test_critique_does_not_flag_a_single_failure(isolated_data_dir):
    _record("fix target.py", False)
    assert critique_recent_failures() == []


def test_critique_flags_a_repeated_goal_failure(isolated_data_dir):
    _record("fix target.py", False)
    _record("fix target.py", False)
    _record("fix other.py", False)

    findings = critique_recent_failures()

    goal_findings = [f for f in findings if f["pattern"] == "repeated_goal_failure"]
    assert len(goal_findings) == 1
    assert goal_findings[0]["goal"] == "fix target.py"
    assert goal_findings[0]["count"] == 2


def test_critique_flags_a_stage_failure_by_last_tool(isolated_data_dir):
    _record("fix a", False, tools_used=["repo.audit", "test.run"])
    _record("fix b", False, tools_used=["repo.audit", "test.run"])

    findings = critique_recent_failures()

    stage_findings = [f for f in findings if f["pattern"] == "stage_failure"]
    assert len(stage_findings) == 1
    assert stage_findings[0]["tool"] == "test.run"
    assert stage_findings[0]["count"] == 2


def test_critique_ranks_the_most_frequent_pattern_first(isolated_data_dir):
    _record("fix a", False)
    _record("fix a", False)
    _record("fix a", False)
    _record("fix b", False, tools_used=["test.run"])
    _record("fix c", False, tools_used=["test.run"])

    findings = critique_recent_failures()

    assert findings[0]["count"] == 3
    assert findings[0]["pattern"] == "repeated_goal_failure"


def test_critique_filters_by_agent(isolated_data_dir):
    _record("fix a", False, agent="self-improve")
    _record("fix a", False, agent="self-improve")
    _record("fix a", False, agent="other-agent")
    _record("fix a", False, agent="other-agent")

    findings = critique_recent_failures(agent="self-improve")

    assert len(findings) == 1
    assert findings[0]["count"] == 2


def test_critique_respects_a_custom_min_pattern_count(isolated_data_dir):
    _record("fix a", False)
    _record("fix a", False)

    assert critique_recent_failures(min_pattern_count=3) == []
    assert len(critique_recent_failures(min_pattern_count=2)) == 1
