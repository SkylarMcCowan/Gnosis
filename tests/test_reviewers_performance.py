"""Regression tests for reviewers/performance.py - fake coding_chat_fn, no
real model calls.
"""
from reviewers.performance import review_performance


def test_review_performance_forwards_the_content_and_returns_the_reply():
    calls = []

    def fake_chat(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return "[Minor] Nested loop could be flattened."

    result = review_performance("for x in a:\n    for y in b:\n        pass", fake_chat)

    assert result == "[Minor] Nested loop could be flattened."
    assert "for x in a" in calls[0][1]
    assert "Performance Reviewer" in calls[0][0]


def test_review_performance_returns_a_fallback_when_the_model_does_not_respond():
    result = review_performance("x = 1", lambda s, u: None)
    assert result.startswith("[OK]")
    assert "unavailable" in result
