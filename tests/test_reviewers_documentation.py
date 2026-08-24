"""Regression tests for reviewers/documentation.py - fake coding_chat_fn,
no real model calls.
"""
from reviewers.documentation import review_documentation


def test_review_documentation_forwards_the_content_and_returns_the_reply():
    calls = []

    def fake_chat(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return "[OK] Clear enough to review as-is."

    result = review_documentation("def add(a, b):\n    return a + b\n", fake_chat)

    assert result == "[OK] Clear enough to review as-is."
    assert "def add" in calls[0][1]
    assert "Documentation Reviewer" in calls[0][0]


def test_review_documentation_returns_a_fallback_when_the_model_does_not_respond():
    result = review_documentation("x = 1", lambda s, u: None)
    assert result.startswith("[OK]")
    assert "unavailable" in result
