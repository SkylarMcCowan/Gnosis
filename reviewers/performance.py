"""Performance Reviewer: looks at a diff/code change for obvious
efficiency red flags - a model call, same reasoning as security.py.
"""

_FALLBACK = "[OK] Performance review unavailable (model did not respond)."


def review_performance(content, coding_chat_fn):
    system_prompt = (
        "You are a Performance Reviewer looking at a code change. Identify any real, obvious "
        "performance concerns: accidental quadratic-or-worse loops, unnecessary repeated work "
        "inside a loop that could be hoisted out, reading a whole large file/collection when a "
        "streaming or partial read would do, or similarly clear inefficiencies. Do not speculate "
        "about micro-optimizations or invent concerns that aren't really there. Label your "
        "overall assessment with exactly one tag at the very start of your reply: [OK] if you "
        "see no real concern, [Minor] for something small worth a passing mention, or [Concern] "
        "for something a human should look at closely. Be terse - a few sentences at most, no "
        "preamble. If there's nothing to flag, reply with exactly: [OK] No performance concerns found."
    )
    user_prompt = f"Code to review:\n\n{content[:4000]}"
    raw = coding_chat_fn(system_prompt, user_prompt)
    return raw.strip() if raw else _FALLBACK
