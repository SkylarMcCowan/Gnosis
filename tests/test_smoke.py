"""Phase 0 smoke tests: launch, model connection, and basic conversation.

These exist to prove webagent.py still works end-to-end before any refactor
touches it, per the roadmap's rule: "don't refactor something until there's
at least one way to verify it still works."
"""
import pytest

import webagent


def test_gnosis_launches_successfully():
    """Importing webagent.py must not raise, and its guarded __main__ block
    (venv relaunch) must not have fired during the import triggered by test
    collection."""
    assert hasattr(webagent, "main")
    assert callable(webagent.main)


def test_model_registry_is_well_formed():
    assert set(webagent.MODELS) == {"main", "search", "unfiltered", "coding"}
    assert all(isinstance(v, str) and v for v in webagent.MODELS.values())


def test_ollama_connection():
    """Real connectivity check against the local Ollama server. Skips (rather
    than fails) when no server is reachable, since that's an environment
    fact, not a code regression."""
    if webagent.ollama is None:
        pytest.skip("ollama package is not importable in this environment")
    try:
        available = {m["model"] for m in webagent.ollama.list().get("models", [])}
    except Exception as exc:
        pytest.skip(f"Ollama server is not reachable: {exc}")
    missing = set(webagent.MODELS.values()) - available
    assert not missing, f"Ollama is reachable but missing pulled models: {missing}"


def test_basic_conversation(fake_ollama_chat):
    """chat_response() is the programmatic entry point behind every UI
    (CLI loop and webagent_gui.py both funnel through it) - this exercises
    the default (non-research, non-agent) path end to end against a fake
    model. Two model calls, not one: _select_tool_action's local-capability
    check now runs on every turn (its fake, non-JSON reply is correctly
    treated as "no tool needed" - see test_tool_actions.py), then the real
    conversational reply streams."""
    reply = webagent.chat_response("Hello, are you there?")
    assert reply == fake_ollama_chat.reply
    assert len(fake_ollama_chat.calls) == 2
    assert all(call["model"] == webagent.MODELS["main"] for call in fake_ollama_chat.calls)

    roles = [m["role"] for m in webagent.context.assistant_convo]
    assert roles[-2:] == ["user", "assistant"]


def test_basic_conversation_empty_prompt_is_a_noop(fake_ollama_chat):
    assert webagent.chat_response("   ") == ""
    assert fake_ollama_chat.calls == []
