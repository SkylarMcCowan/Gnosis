"""Regression tests for observability/metrics.py - real queries over
memory.experience and core.activity_log's recorded data.
"""
from core.activity_log import record_activity
from memory.experience import build_experience, record_experience
from observability.metrics import (
    search_quality_stats, self_improve_target_file_stats,
    task_completion_stats, tool_usage_stats,
)


def test_tool_usage_stats_counts_uses_and_success_rate(isolated_data_dir):
    record_experience(build_experience(goal="a", success=True, tools_used=["repo.audit", "test.run"]))
    record_experience(build_experience(goal="b", success=False, tools_used=["repo.audit"]))

    stats = tool_usage_stats()

    assert stats["repo.audit"] == {"used": 2, "attempted": 2, "succeeded": 1, "success_rate": 0.5}
    assert stats["test.run"] == {"used": 1, "attempted": 1, "succeeded": 1, "success_rate": 1.0}


def test_tool_usage_stats_excludes_not_attempted_from_the_rate(isolated_data_dir):
    """success=None ("not attempted," e.g. a blocked cycle) must not count
    as a failure - it's excluded from the rate's denominator entirely."""
    record_experience(build_experience(goal="blocked", success=None, tools_used=["git.status"]))
    record_experience(build_experience(goal="blocked again", success=None, tools_used=["git.status"]))

    stats = tool_usage_stats()

    assert stats["git.status"] == {"used": 2, "attempted": 0, "succeeded": 0, "success_rate": None}


def test_tool_usage_stats_filters_by_agent(isolated_data_dir):
    record_experience(build_experience(goal="a", success=True, tools_used=["repo.audit"], agent="self-improve"))
    record_experience(build_experience(goal="b", success=True, tools_used=["repo.audit"], agent="tool-generator"))

    stats = tool_usage_stats(agent="self-improve")

    assert stats["repo.audit"]["used"] == 1


def test_tool_usage_stats_respects_window(isolated_data_dir):
    for i in range(3):
        record_experience(build_experience(goal=f"g{i}", success=False, tools_used=["repo.audit"]))
    record_experience(build_experience(goal="last", success=True, tools_used=["test.run"]))

    stats = tool_usage_stats(window=1)

    assert "repo.audit" not in stats
    assert stats["test.run"]["used"] == 1


def test_tool_usage_stats_empty_with_no_data(isolated_data_dir):
    assert tool_usage_stats() == {}


def test_search_quality_stats_computes_zero_result_rate_and_average(isolated_data_dir):
    record_activity("SEARCH_COMPLETED", query="a", result_count=5)
    record_activity("SEARCH_COMPLETED", query="b", result_count=0)

    stats = search_quality_stats()

    assert stats["total_searches"] == 2
    assert stats["zero_result_searches"] == 1
    assert stats["zero_result_rate"] == 0.5
    assert stats["avg_result_count"] == 2.5


def test_search_quality_stats_empty_with_no_data(isolated_data_dir):
    stats = search_quality_stats()
    assert stats == {"total_searches": 0, "zero_result_searches": 0, "zero_result_rate": None, "avg_result_count": None}


def test_task_completion_stats_counts_by_agent(isolated_data_dir):
    record_activity("TASK_COMPLETED", agent_name="research", user_input="x", response="y")
    record_activity("TASK_COMPLETED", agent_name="research", user_input="x", response="y")
    record_activity("TASK_COMPLETED", agent_name="ethics", user_input="x", response="y")

    stats = task_completion_stats()

    assert stats["total_completed"] == 3
    assert stats["by_agent"] == {"research": 2, "ethics": 1}


def test_self_improve_target_file_stats_parses_the_goal_string(isolated_data_dir):
    record_experience(build_experience(goal="Fix target.py: add() is wrong", success=True, agent="self-improve"))
    record_experience(build_experience(goal="Fix target.py: still wrong", success=False, agent="self-improve"))
    record_experience(build_experience(goal="Fix other.py: unrelated", success=True, agent="self-improve"))
    # A non-"Fix ..." goal (e.g. candidate selection) is ignored, not miscounted.
    record_experience(build_experience(goal="Find a self-improvement candidate", success=None, agent="self-improve"))
    # A different agent's goal never counts toward self-improve's own file stats.
    record_experience(build_experience(goal="Fix target.py: from another agent", success=True, agent="tool-generator"))

    stats = self_improve_target_file_stats()

    assert stats["target.py"] == {"attempts": 2, "succeeded": 1}
    assert stats["other.py"] == {"attempts": 1, "succeeded": 1}
