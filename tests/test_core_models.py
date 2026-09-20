"""Regression tests for core/models.py, the first Phase 1 extraction from
webagent.py: the Ollama import/fallback, the MODELS registry, and the chat()
funnel every call site in webagent.py now goes through instead of calling
ollama.chat() directly.
"""
import pytest

from core import models as core_models


def test_models_registry_is_well_formed():
    assert set(core_models.MODELS) == {"main", "search", "unfiltered", "coding", "fast"}
    assert all(isinstance(v, str) and v for v in core_models.MODELS.values())


def test_is_available_reflects_ollama_import():
    assert core_models.is_available() == (core_models.ollama is not None)


def test_chat_raises_clearly_when_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(core_models, "ollama", None)
    with pytest.raises(RuntimeError, match="Ollama client is unavailable"):
        core_models.chat(model="main", messages=[{"role": "user", "content": "hi"}])


def test_chat_forwards_to_ollama_when_available(monkeypatch):
    calls = []

    class FakeOllama:
        @staticmethod
        def chat(model, messages, stream=False, **kwargs):
            calls.append({"model": model, "messages": messages, "stream": stream, **kwargs})
            return {"message": {"content": "canned reply"}}

    monkeypatch.setattr(core_models, "ollama", FakeOllama)

    result = core_models.chat(model="main", messages=[{"role": "user", "content": "hi"}])

    assert result == {"message": {"content": "canned reply"}}
    # "main" here is the literal string passed in (not a real Ollama model
    # name), so it isn't a MODEL_CONTEXT key - falls back to DEFAULT_CONTEXT.
    assert calls == [{
        "model": "main", "messages": [{"role": "user", "content": "hi"}], "stream": False,
        "options": {"num_ctx": core_models.DEFAULT_CONTEXT},
    }]


def test_chat_uses_the_per_model_context_window(monkeypatch):
    calls = []

    class FakeOllama:
        @staticmethod
        def chat(model, messages, stream=False, **kwargs):
            calls.append(kwargs)
            return {"message": {"content": "canned reply"}}

    monkeypatch.setattr(core_models, "ollama", FakeOllama)

    core_models.chat(model="qwen3.5:4b", messages=[{"role": "user", "content": "hi"}])

    assert calls == [{"options": {"num_ctx": core_models.MODEL_CONTEXT["qwen3.5:4b"]}}]


def test_chat_caller_supplied_options_take_precedence(monkeypatch):
    calls = []

    class FakeOllama:
        @staticmethod
        def chat(model, messages, stream=False, **kwargs):
            calls.append(kwargs)
            return {"message": {"content": "canned reply"}}

    monkeypatch.setattr(core_models, "ollama", FakeOllama)

    core_models.chat(model="qwen3.5:4b", messages=[], options={"num_ctx": 123, "temperature": 0.5})

    assert calls == [{"options": {"num_ctx": 123, "temperature": 0.5}}]


def test_pull_all_returns_false_when_ollama_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(core_models, "ollama", None)

    result = core_models.pull_all()

    assert result is False
    assert "unavailable" in capsys.readouterr().out.lower()


def test_pull_all_pulls_every_model(monkeypatch):
    pulled = []

    class FakeOllama:
        @staticmethod
        def pull(model):
            pulled.append(model)

    monkeypatch.setattr(core_models, "ollama", FakeOllama)

    result = core_models.pull_all()

    assert result is True
    assert pulled == list(core_models.MODELS.values())


def test_webagent_reexports_the_same_models_registry():
    import webagent
    assert webagent.MODELS is core_models.MODELS
    assert webagent.ollama is core_models.ollama
    assert webagent.model_chat is core_models.chat


def test_transport_timeout_propagates_without_retrying(monkeypatch):
    import httpx
    import ollama
    calls = []
    def stalled(request):
        calls.append(request)
        raise httpx.ReadTimeout('Model stalled', request=request)
    client = ollama.Client(host='http://127.0.0.1:11434', transport=httpx.MockTransport(stalled), timeout=0.1)
    monkeypatch.setattr(core_models, 'ollama', client)
    with pytest.raises(httpx.ReadTimeout):
        core_models.chat('local-model', [{'role': 'user', 'content': 'hello'}])
    assert len(calls) == 1
