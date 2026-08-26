"""Regression tests for tools/subscriptions/list.py."""
from tools.base import Permission
from tools.subscriptions.list import SubscriptionsListTool


def test_subscriptions_list_forwards_to_the_injected_function():
    calls = []

    def fake_list():
        calls.append(True)
        return [{"type": "team", "name": "Manchester United"}]

    tool = SubscriptionsListTool(fake_list)
    assert tool.execute() == [{"type": "team", "name": "Manchester United"}]
    assert calls == [True]


def test_subscriptions_list_metadata():
    tool = SubscriptionsListTool(lambda: [])
    assert tool.name == "subscriptions.list"
    assert tool.permission == Permission.SAFE
    assert tool.parameters == {}
