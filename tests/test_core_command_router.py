"""Regression tests for core/command_router.py, the generic dispatch
mechanism behind the fourth Phase 1 extraction. Pure unit tests against
CommandRouter itself - no webagent.py involvement, since this module is
deliberately independent of it.
"""
from core.command_router import CommandRouter


def test_register_exact_match_is_case_insensitive():
    router = CommandRouter()
    calls = []
    router.register("/exit", lambda prompt: calls.append(prompt))

    assert router.dispatch("/EXIT") is True
    assert calls == ["/EXIT"]


def test_register_accepts_multiple_patterns_for_one_handler():
    router = CommandRouter()
    calls = []
    router.register(("/historian", "/historian preview"), lambda prompt: calls.append(prompt))

    assert router.dispatch("/historian preview") is True
    assert router.dispatch("/historian") is True
    assert calls == ["/historian preview", "/historian"]


def test_register_prefix_matches_with_arguments():
    router = CommandRouter()
    calls = []
    router.register_prefix("/job", lambda prompt: calls.append(prompt))

    assert router.dispatch("/job ethics") is True
    assert router.dispatch("/job") is True
    assert calls == ["/job ethics", "/job"]


def test_exact_match_takes_priority_over_a_prefix():
    router = CommandRouter()
    order = []
    router.register_prefix("/cron", lambda prompt: order.append("prefix"))
    router.register("/cron", lambda prompt: order.append("exact"))

    router.dispatch("/cron")

    assert order == ["exact"]


def test_dispatch_returns_false_when_nothing_matches():
    router = CommandRouter()
    router.register("/exit", lambda prompt: None)

    assert router.dispatch("/not_a_real_command") is False


def test_unrelated_prefixes_do_not_collide():
    router = CommandRouter()
    calls = []
    router.register_prefix("/showpath", lambda prompt: calls.append("showpath"))
    router.register_prefix("/delpath", lambda prompt: calls.append("delpath"))

    router.dispatch("/delpath astronomy")

    assert calls == ["delpath"]
