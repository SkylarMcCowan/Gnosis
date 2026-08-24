"""Regression tests for reviewers/panel.py's run_review_panel - fake
coding_chat_fn, no real model calls.
"""
from reviewers.panel import run_review_panel


def test_run_review_panel_runs_all_three_reviewers():
    def fake_chat(system_prompt, user_prompt):
        if "Security" in system_prompt:
            return "[OK] no issues"
        if "Performance" in system_prompt:
            return "[Minor] a small thing"
        if "Documentation" in system_prompt:
            return "[Concern] unclear"
        return "[OK] fallback"

    result = run_review_panel("some code", fake_chat)

    assert result == {
        "security": "[OK] no issues",
        "performance": "[Minor] a small thing",
        "documentation": "[Concern] unclear",
    }


def test_run_review_panel_forwards_the_same_content_to_every_reviewer():
    seen = []
    run_review_panel("the exact content", lambda s, u: seen.append(u) or "[OK] fine")
    assert len(seen) == 3
    assert all("the exact content" in u for u in seen)
