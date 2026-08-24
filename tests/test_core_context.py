"""Regression tests for core/context.py, the third and largest Phase 1
extraction: the shared session-state object that replaced nine separate
webagent.py module globals (assistant_convo, current_agent, and seven mode
flags), each previously mutated via its own `global` declaration.
"""
from core.context import Context, context as shared_context


def test_context_defaults_match_the_original_globals():
    ctx = Context()
    assert ctx.assistant_convo == []
    assert ctx.current_agent is None
    assert ctx.voice_mode is False
    assert ctx.tts_mode is False
    assert ctx.web_search_mode is True
    assert ctx.reasoning_mode is False
    assert ctx.deep_think_mode is False
    assert ctx.unfiltered_mode is False
    assert ctx.coding_mode is False


def test_each_context_instance_is_independent():
    a, b = Context(), Context()
    a.current_agent = "ethics"
    assert b.current_agent is None


def test_webagent_shares_the_single_context_instance():
    import webagent
    assert webagent.context is shared_context


def test_mutating_context_through_one_reference_is_visible_through_another():
    """The actual bug this extraction fixes: two modules holding the *same*
    context object (not a captured value) must always see each other's
    writes, unlike the old `from webagent import assistant_convo` pattern
    tarot.py used, which froze a reference at import time."""
    import webagent

    handle_a = webagent.context
    webagent.context.current_agent = "ethics"
    assert handle_a.current_agent == "ethics"
