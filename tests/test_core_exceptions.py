"""Regression tests for core/exceptions.py, the sixth Phase 1 extraction."""
import pytest

from core.exceptions import GnosisError, ModelUnavailableError


def test_model_unavailable_error_is_a_gnosis_error():
    assert issubclass(ModelUnavailableError, GnosisError)


def test_model_unavailable_error_is_also_a_runtime_error():
    """Callers written before this hierarchy existed catch bare RuntimeError -
    that must keep working."""
    assert issubclass(ModelUnavailableError, RuntimeError)
    with pytest.raises(RuntimeError):
        raise ModelUnavailableError("no model backend")


def test_core_models_chat_raises_the_specific_type(monkeypatch):
    from core import models as core_models
    monkeypatch.setattr(core_models, "ollama", None)
    with pytest.raises(ModelUnavailableError):
        core_models.chat(model="main", messages=[])


def test_webagent_chat_response_raises_the_specific_type(monkeypatch):
    import webagent
    monkeypatch.setattr(webagent, "ollama", None)
    with pytest.raises(ModelUnavailableError):
        webagent.chat_response("hello")
