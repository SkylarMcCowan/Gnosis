"""Regression tests for reviewers/security.py - fake coding_chat_fn, no
real model calls.
"""
from reviewers.security import review_security


def test_review_security_forwards_the_content_and_returns_the_reply():
    calls = []

    def fake_chat(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return "[Concern] Hardcoded API key found."

    result = review_security("API_KEY = 'sk-12345'", fake_chat)

    assert result == "[Concern] Hardcoded API key found."
    assert "API_KEY = 'sk-12345'" in calls[0][1]
    assert "Security Reviewer" in calls[0][0]


def test_review_security_returns_a_fallback_when_the_model_does_not_respond():
    result = review_security("x = 1", lambda s, u: None)
    assert result.startswith("[OK]")
    assert "unavailable" in result


def test_review_security_truncates_very_long_content():
    captured = {}

    def fake_chat(system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return "[OK] fine"

    review_security("x" * 10000, fake_chat)
    assert len(captured["user_prompt"]) < 10000
