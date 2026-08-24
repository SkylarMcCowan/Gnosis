"""Regression tests for core/orchestrator.py, the fifth Phase 1 extraction:
the generic read/dispatch/fallback loop shape behind webagent.py's main().
"""
from core.command_router import CommandRouter
from core.orchestrator import Orchestrator


def test_run_once_returns_false_when_read_input_yields_nothing():
    calls = []
    orchestrator = Orchestrator(
        read_input=lambda: None,
        before_dispatch=lambda prompt: calls.append(("before", prompt)),
        router=CommandRouter(),
        on_unmatched=lambda prompt: calls.append(("unmatched", prompt)),
    )

    assert orchestrator.run_once() is False
    assert calls == []


def test_run_once_dispatches_to_a_matching_command():
    calls = []
    router = CommandRouter()
    router.register("/exit", lambda prompt: calls.append(("handled", prompt)))
    orchestrator = Orchestrator(
        read_input=lambda: "/exit",
        before_dispatch=lambda prompt: calls.append(("before", prompt)),
        router=router,
        on_unmatched=lambda prompt: calls.append(("unmatched", prompt)),
    )

    assert orchestrator.run_once() is True
    assert calls == [("before", "/exit"), ("handled", "/exit")]


def test_run_once_falls_back_when_nothing_matches():
    calls = []
    orchestrator = Orchestrator(
        read_input=lambda: "hello there",
        before_dispatch=lambda prompt: calls.append(("before", prompt)),
        router=CommandRouter(),
        on_unmatched=lambda prompt: calls.append(("unmatched", prompt)),
    )

    assert orchestrator.run_once() is True
    assert calls == [("before", "hello there"), ("unmatched", "hello there")]


def test_run_forever_calls_run_once_until_it_raises():
    calls = []

    class Boom(Exception):
        pass

    def read_input():
        calls.append(1)
        if len(calls) >= 3:
            raise Boom
        return None

    orchestrator = Orchestrator(
        read_input=read_input,
        before_dispatch=lambda prompt: None,
        router=CommandRouter(),
        on_unmatched=lambda prompt: None,
    )

    try:
        orchestrator.run_forever()
    except Boom:
        pass

    assert len(calls) == 3
