"""Documentation Reviewer: checks whether a change is clear enough to
review on its own - a model call, same reasoning as security.py.
"""

_FALLBACK = "[OK] Documentation review unavailable (model did not respond)."


def review_documentation(content, coding_chat_fn):
    system_prompt = (
        "You are a Documentation Reviewer looking at a code change. Judge only whether the "
        "change is clear enough for a human reviewer to understand what it does and why, "
        "without needing to guess - e.g. a non-obvious decision left completely unexplained, "
        "or a new function/class with no docstring where its purpose genuinely isn't clear from "
        "its name alone. Do not ask for documentation that isn't actually needed - well-named, "
        "self-evident code needs no comment. Label your overall assessment with exactly one tag "
        "at the very start of your reply: [OK] if it's clear enough as-is, [Minor] for a small "
        "clarity gap worth a passing mention, or [Concern] for something genuinely hard to "
        "review without more explanation. Be terse - a few sentences at most, no preamble. If "
        "there's nothing to flag, reply with exactly: [OK] Clear enough to review as-is."
    )
    user_prompt = f"Code to review:\n\n{content[:4000]}"
    raw = coding_chat_fn(system_prompt, user_prompt)
    return raw.strip() if raw else _FALLBACK
