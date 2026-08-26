"""Regression tests for core/subscriptions.py - add_subscription/
list_subscriptions/get_subscription/remove_subscription.
"""
import os

import pytest

from core.subscriptions import add_subscription, get_subscription, list_subscriptions, remove_subscription


def test_add_and_list_subscriptions_round_trip(isolated_data_dir):
    add_subscription("team", "Manchester United", metadata={"team_id": "360"})
    add_subscription("topic", "Formula 1")

    records = list_subscriptions()

    assert len(records) == 2
    assert records[0]["type"] == "team"
    assert records[0]["name"] == "Manchester United"
    assert records[0]["metadata"] == {"team_id": "360"}
    assert "id" in records[0]
    assert "created_at" in records[0]
    assert records[1]["type"] == "topic"
    assert records[1]["metadata"] == {}


def test_list_subscriptions_filters_by_type(isolated_data_dir):
    add_subscription("team", "Manchester United")
    add_subscription("topic", "Formula 1")
    add_subscription("team", "Arsenal")

    assert [r["name"] for r in list_subscriptions(sub_type="team")] == ["Manchester United", "Arsenal"]


def test_list_subscriptions_returns_empty_list_when_no_file_exists(isolated_data_dir):
    assert list_subscriptions() == []


def test_list_subscriptions_never_creates_the_directory(isolated_data_dir):
    """Same lesson as core/activity_log.py's read/write split: a read must
    never have the side effect of creating on-disk state that wasn't
    there."""
    list_subscriptions()
    assert not os.path.exists(os.path.join(isolated_data_dir, "subscriptions"))


def test_add_subscription_rejects_an_unknown_type(isolated_data_dir):
    with pytest.raises(ValueError):
        add_subscription("player", "Some Player")


def test_add_subscription_accepts_the_weather_type(isolated_data_dir):
    record = add_subscription("weather", "Tucson, Arizona, United States", metadata={"location": "Tucson, Arizona, United States"})
    assert record["type"] == "weather"
    assert list_subscriptions(sub_type="weather") == [record]


def test_add_subscription_rejects_an_empty_name(isolated_data_dir):
    with pytest.raises(ValueError):
        add_subscription("team", "   ")


def test_add_subscription_rejects_a_case_insensitive_duplicate(isolated_data_dir):
    add_subscription("team", "Manchester United")
    with pytest.raises(ValueError):
        add_subscription("team", "manchester united")


def test_add_subscription_allows_the_same_name_across_different_types(isolated_data_dir):
    add_subscription("team", "Arsenal")
    add_subscription("topic", "Arsenal")  # different type - not a duplicate
    assert len(list_subscriptions()) == 2


def test_get_subscription_finds_by_id(isolated_data_dir):
    record = add_subscription("team", "Manchester United")
    assert get_subscription(record["id"]) == record


def test_get_subscription_returns_none_for_an_unknown_id(isolated_data_dir):
    assert get_subscription("nonexistent") is None


def test_remove_subscription_removes_the_matching_record(isolated_data_dir):
    record = add_subscription("team", "Manchester United")
    add_subscription("topic", "Formula 1")

    removed = remove_subscription(record["id"])

    assert removed is True
    assert [r["name"] for r in list_subscriptions()] == ["Formula 1"]


def test_remove_subscription_returns_false_for_an_unknown_id(isolated_data_dir):
    add_subscription("team", "Manchester United")
    assert remove_subscription("nonexistent") is False
    assert len(list_subscriptions()) == 1


def test_can_add_again_after_removing(isolated_data_dir):
    record = add_subscription("team", "Manchester United")
    remove_subscription(record["id"])

    add_subscription("team", "Manchester United")  # no longer a duplicate

    assert len(list_subscriptions()) == 1
