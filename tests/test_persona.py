"""Regression tests for /persona and /profile persona (webagent.py:1763-1811)."""
import webagent


def test_set_user_persona_accepts_a_supported_value(isolated_data_dir):
    success, result = webagent.set_user_persona("cheery")
    assert success is True
    assert result["persona"] == "cheery"
    assert webagent.load_user_profile()["persona"] == "cheery"


def test_set_user_persona_accepts_multiple_comma_separated_values(isolated_data_dir):
    success, result = webagent.set_user_persona("happy and direct")
    assert success is True
    assert result["persona"] == "happy, direct"


def test_set_user_persona_rejects_unknown_value(isolated_data_dir):
    success, supported = webagent.set_user_persona("mysterious")
    assert success is False
    assert "neutral" in supported


def test_format_persona_transition_from_neutral():
    text = webagent.format_persona_transition("neutral", "happy")
    assert "Happy" in text
    assert "Neutral" in text


def test_format_persona_transition_same_persona_is_a_noop_message():
    text = webagent.format_persona_transition("calm", "calm")
    assert "already on stage" in text
