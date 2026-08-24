"""Regression tests for core/events.py, the seventh and final Phase 1
extraction: a generic publish/subscribe event bus. Pure scaffolding for
Phase 12 - nothing in webagent.py wires into this yet, so these tests
exercise EventBus itself in isolation.
"""
from core.events import EventBus


def test_publish_calls_every_subscriber_with_the_payload():
    bus = EventBus()
    received = []
    bus.subscribe("TASK_COMPLETED", lambda **payload: received.append(payload))
    bus.subscribe("TASK_COMPLETED", lambda **payload: received.append(payload))

    bus.publish("TASK_COMPLETED", task_id="abc", success=True)

    assert received == [{"task_id": "abc", "success": True}, {"task_id": "abc", "success": True}]


def test_publish_with_no_subscribers_is_a_noop():
    bus = EventBus()
    bus.publish("NOBODY_LISTENING", x=1)  # must not raise


def test_subscribers_to_different_events_do_not_cross_fire():
    bus = EventBus()
    received = []
    bus.subscribe("A", lambda: received.append("A"))
    bus.subscribe("B", lambda: received.append("B"))

    bus.publish("A")

    assert received == ["A"]


def test_unsubscribe_stops_further_notifications():
    bus = EventBus()
    received = []

    def handler(**payload):
        received.append(payload)

    bus.subscribe("X", handler)
    bus.publish("X", n=1)
    bus.unsubscribe("X", handler)
    bus.publish("X", n=2)

    assert received == [{"n": 1}]


def test_unsubscribe_an_unregistered_handler_is_a_noop():
    bus = EventBus()
    bus.unsubscribe("NEVER_SUBSCRIBED", lambda: None)  # must not raise


def test_handler_that_unsubscribes_during_publish_does_not_break_that_publish():
    bus = EventBus()
    received = []

    def self_removing_handler(**payload):
        received.append(payload)
        bus.unsubscribe("X", self_removing_handler)

    bus.subscribe("X", self_removing_handler)
    bus.subscribe("X", lambda **payload: received.append(payload))

    bus.publish("X", n=1)

    assert len(received) == 2
