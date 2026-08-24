"""Shared "ask the user a clarifying question" primitive.

Any pipeline that asks the local model for a structured JSON decision can
route the call through call_agent_json() below to gain the ability to pause
and ask the user a clarifying question before committing to an answer - the
same pattern Claude Code's own AskUserQuestion tool uses. This module has no
GUI dependency: the terminal falls back to input(), and the GUI registers a
blocking asker via set_ui_asker().
"""

import json
import re

_ui_asker = None


def set_ui_asker(fn):
    """Register a callable fn(questions) -> {question: answer}. Pass None to
    revert to the terminal input() fallback."""
    global _ui_asker
    _ui_asker = fn


def ask_user_question(questions):
    """questions: list of {"question": str, "options": list[str] | None}.
    Returns a dict mapping each question string to the user's answer."""
    if _ui_asker is not None:
        return _ui_asker(questions)

    answers = {}
    for q in questions:
        question_text = q.get("question", "").strip()
        if not question_text:
            continue
        print(f"\n[Clarifying question] {question_text}")
        options = q.get("options") or []
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        answers[question_text] = input("> ").strip()
    return answers


CLARIFY_INSTRUCTION = (
    '\n\nIf you need information from the user before you can answer correctly, '
    'respond with EXACTLY this JSON and nothing else: '
    '{"clarify": [{"question": "...", "options": ["...", "..."]}]} '
    '("options" is optional). Only ask when genuinely necessary, and ask at most '
    '3 questions at once.'
)


def _extract_json(content):
    match = re.search(r"\{.*\}", content, re.DOTALL)
    return json.loads(match.group(0) if match else content)


def call_agent_json(chat_fn, system_prompt, extra_messages=None, max_clarify_rounds=2):
    """Call the model for a structured JSON decision, transparently handling
    any clarifying-question round trip.

    chat_fn: callable(messages) -> str (the model's raw text reply).
    Returns the parsed JSON dict on success, or None if it could never be
    parsed as JSON.
    """
    messages = [{"role": "system", "content": system_prompt + CLARIFY_INSTRUCTION}]
    if extra_messages:
        messages.extend(extra_messages)

    for _ in range(max_clarify_rounds + 1):
        content = chat_fn(messages)
        try:
            parsed = _extract_json(content)
        except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
            return None

        if isinstance(parsed, dict) and "clarify" in parsed:
            answers = ask_user_question(parsed["clarify"])
            qa_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items())
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Here are the answers to your questions:\n{qa_text}"})
            continue

        return parsed

    return parsed
