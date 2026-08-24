"""Regression tests for core/activity_log.py - record_activity/load_activity.
"""
import os

from core.activity_log import load_activity, record_activity


def test_record_and_load_activity_round_trip(isolated_data_dir):
    record_activity("SEARCH_COMPLETED", query="stoicism", result_count=5)
    record_activity("MEMORY_CREATED", agent_name="research")

    entries = load_activity()

    assert len(entries) == 2
    assert entries[0]["event"] == "SEARCH_COMPLETED"
    assert entries[0]["query"] == "stoicism"
    assert entries[1]["event"] == "MEMORY_CREATED"
    assert "timestamp" in entries[0]


def test_load_activity_filters_by_event_name(isolated_data_dir):
    record_activity("SEARCH_COMPLETED", query="a")
    record_activity("MEMORY_CREATED", agent_name="research")
    record_activity("SEARCH_COMPLETED", query="b")

    entries = load_activity(event_name="SEARCH_COMPLETED")

    assert [e["query"] for e in entries] == ["a", "b"]


def test_load_activity_respects_limit(isolated_data_dir):
    for i in range(5):
        record_activity("SEARCH_COMPLETED", query=f"q{i}")

    entries = load_activity(limit=2)

    assert [e["query"] for e in entries] == ["q3", "q4"]


def test_load_activity_returns_empty_list_when_no_log_exists(isolated_data_dir):
    assert load_activity() == []


def test_load_activity_never_creates_the_directory(isolated_data_dir):
    """Same lesson as memory/experience.py's real bug: a read must never
    have the side effect of creating on-disk state that wasn't there."""
    load_activity()
    assert not os.path.exists(os.path.join(isolated_data_dir, "activity"))
