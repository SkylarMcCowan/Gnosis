"""Security Reviewer: looks at a diff/code change for real security
concerns - not a linter, a model call, since spotting an actual risk
(vs. a superficially similar but harmless pattern) needs semantic
judgment a regex can't reliably provide.
"""

_FALLBACK = "[OK] Security review unavailable (model did not respond)."


def review_security(content, coding_chat_fn):
    system_prompt = (
        "You are a Security Reviewer looking at a code change. Identify any real security "
        "concerns: hardcoded secrets/credentials, shell/SQL/command injection risk, unsafe "
        "eval/exec of untrusted input, path traversal, disabled certificate/TLS verification, "
        "or similarly risky patterns. Ignore purely stylistic issues - only real risk. Label "
        "your overall assessment with exactly one tag at the very start of your reply: "
        "[OK] if you see no real concern, [Minor] for a small risk worth a passing mention, or "
        "[Concern] for something a human should look at closely before applying this change. "
        "Be terse - a few sentences at most, no preamble. If there's nothing to flag, reply "
        "with exactly: [OK] No security concerns found."
    )
    user_prompt = f"Code to review:\n\n{content[:4000]}"
    raw = coding_chat_fn(system_prompt, user_prompt)
    return raw.strip() if raw else _FALLBACK
