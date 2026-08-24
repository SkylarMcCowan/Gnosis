"""Regression tests for reviewers/release_manager.py's summarize_reviews -
purely deterministic, no model call at all.
"""
from reviewers.release_manager import summarize_reviews


def test_not_recommended_when_tests_did_not_pass():
    result = summarize_reviews(["[OK] fine", "[OK] fine"], tests_passed=False)
    assert result.startswith("NOT RECOMMENDED")


def test_not_recommended_overrides_even_when_every_reviewer_says_ok():
    result = summarize_reviews(["[OK] fine", "[OK] fine", "[OK] fine"], tests_passed=False)
    assert "NOT RECOMMENDED" in result


def test_flags_review_carefully_when_any_reviewer_raises_a_concern():
    result = summarize_reviews(["[OK] fine", "[Concern] hardcoded secret"], tests_passed=True)
    assert "Review carefully" in result


def test_looks_reasonable_when_tests_pass_and_nothing_is_flagged():
    result = summarize_reviews(["[OK] fine", "[Minor] small nit"], tests_passed=True)
    assert "Looks reasonable" in result


def test_handles_an_empty_reviews_iterable():
    result = summarize_reviews([], tests_passed=True)
    assert "Looks reasonable" in result
