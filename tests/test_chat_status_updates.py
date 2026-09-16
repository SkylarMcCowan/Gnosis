"""Regression tests for the chat-turn status-update channel
(context.status_callback / _emit_status), added so a UI (the GUI's status
label) can show what's happening between the user's message and the reply,
instead of that information only ever reaching a terminal print. See
chat_response's docstring for why this is a context attribute set for the
duration of one call rather than a callback threaded through every nested
function (search_web, model_directed_web_research, _resolve_stock_symbol, ...).
"""
import webagent


def test_emit_status_is_a_noop_when_nothing_is_listening():
    webagent.context.status_callback = None
    webagent._emit_status("should not raise")  # no assertion needed - just must not raise


def test_emit_status_forwards_to_the_registered_callback():
    seen = []
    webagent.context.status_callback = seen.append
    try:
        webagent._emit_status("Searching the web: test query")
    finally:
        webagent.context.status_callback = None
    assert seen == ["Searching the web: test query"]


def test_emit_status_swallows_a_callback_exception():
    def broken_callback(message):
        raise RuntimeError("GUI widget was already destroyed")

    webagent.context.status_callback = broken_callback
    try:
        webagent._emit_status("should not propagate")  # must not raise
    finally:
        webagent.context.status_callback = None


def test_chat_response_wires_on_status_for_the_duration_of_the_call_only(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = False
    fake_ollama_chat.reply = "A drafted answer."
    statuses = []

    assert webagent.context.status_callback is None
    webagent.chat_response("hello", on_status=statuses.append)

    assert "Writing a response..." in statuses
    # Cleared afterward so it never leaks into an unrelated later call.
    assert webagent.context.status_callback is None


def test_chat_response_reports_verifying_facts_when_research_is_used(isolated_data_dir, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = True
    monkeypatch.setattr(
        webagent, "model_directed_web_research",
        lambda prompt: [{"url": "https://example.com", "content": "..."}],
    )
    monkeypatch.setattr(webagent, "fact_check_answer", lambda answer, evidence, user_prompt="": "")
    fake_ollama_chat.reply = "A drafted answer."
    statuses = []

    webagent.chat_response("what is the overview effect?", on_status=statuses.append)

    assert "Verifying facts..." in statuses


def test_chat_response_restores_the_previous_status_callback_on_error(isolated_data_dir, monkeypatch):
    """A status callback registered by an outer/earlier call (or a stale one
    left over from a crashed turn) must not be clobbered permanently by a
    call that itself raises."""
    def boom(prompt, on_chunk, on_sources=None):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(webagent, "_chat_response_impl", boom)
    sentinel = object()
    webagent.context.status_callback = sentinel
    try:
        try:
            webagent.chat_response("hello", on_status=lambda message: None)
        except RuntimeError:
            pass
        assert webagent.context.status_callback is sentinel
    finally:
        webagent.context.status_callback = None
