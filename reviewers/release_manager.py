"""Release Manager: synthesizes the panel's findings into one advisory
recommendation line - deterministic, no model call. A second model call
judging the first models' judgments would just be more unreliable
opinion stacked on unreliable opinion; checking for the [Concern] tag
every reviewer already commits to is a real, checkable signal instead.

Purely advisory: this never changes whether a fix gets applied or a
proposal gets written - see reviewers/__init__.py's stance.
"""


def summarize_reviews(reviews, tests_passed):
    """`reviews` is an iterable of reviewer finding strings (e.g.
    run_review_panel(...).values()). Returns one recommendation line."""
    if not tests_passed:
        return "NOT RECOMMENDED - tests did not pass."
    if any("[Concern]" in review for review in reviews):
        return "Review carefully before applying - at least one reviewer flagged a concern."
    return "Looks reasonable - no reviewer flagged a concern and tests passed."
