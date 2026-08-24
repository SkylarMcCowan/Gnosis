"""GENERATE TESTS: ask an injected coding-chat function to write isolated
unit tests for a just-generated skill.

The prompt instructs the model to fake tool_registry.execute rather than
call it for real - matching the pattern every hand-written skill test in
this codebase already follows (see tests/test_skills_research_topic.py).
This is a request, not a guarantee: validator.py's sandboxed test run adds
a real, code-level safety net (any real tool_registry.execute call raises)
regardless of whether the generated test actually followed this
instruction - see builder/validator.py and builder/__init__.py's safety
stance.
"""
from builder.code_generator import parse_file_block


def generate_tests_for_skill(module_name, class_name, skill_code, coding_chat_fn):
    """Returns (test_rel_path, test_code, reason) - test_code is None with
    a reason on any failure to parse a usable response. The skill is
    always importable as `from generated_skill import {class_name}` - the
    generated test is told this exact import path, rather than left to
    guess one, since validator.py always places the skill file as a
    sibling module named exactly `generated_skill.py`."""
    test_rel_path = f"tests/test_{module_name}.py"
    system_prompt = (
        "You are writing pytest unit tests, in isolation, for a newly generated Gnosis Skill "
        "class. You will be given the skill's full source code. The skill is importable as "
        f"`from generated_skill import {class_name}` (a sibling module next to this test file). "
        "Construct the skill directly and call its execute() method, but you must NEVER let a "
        "real tool run: monkeypatch tool_registry.execute (import it as `from tools.registry "
        "import registry as tool_registry`) with a fake function BEFORE calling execute(), and "
        "assert that execute() called the right tool names with the right arguments, and returned "
        "the right result given the fake's return values. Do not call any real tool under any "
        "circumstance. Respond with ONE complete Python test file's content formatted as:\n\n"
        f"### {test_rel_path}\n```python\n<full file content>\n```\n\n"
        "Output nothing else - no explanation before or after."
    )
    user_prompt = f"Skill source (importable as generated_skill.py):\n\n{skill_code}"
    raw = coding_chat_fn(system_prompt, user_prompt)
    code = parse_file_block(raw, test_rel_path)
    if code is None:
        return None, None, "could not parse a valid test file from the model's response"
    return test_rel_path, code, None
