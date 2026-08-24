"""Regression tests for builder/test_generator.py - fake coding_chat_fn,
no real model calls.
"""
from builder.test_generator import generate_tests_for_skill


def test_generate_tests_for_skill_returns_the_parsed_code():
    test_path = "tests/test_generated_gap.py"
    fake_code = f"### {test_path}\n```python\ndef test_x():\n    assert True\n```\n"

    def fake_chat(system_prompt, user_prompt):
        assert "generated_skill import GapSkill" in system_prompt
        assert "class GapSkill" in user_prompt
        return fake_code

    result_path, code, reason = generate_tests_for_skill(
        "generated_gap", "GapSkill", "class GapSkill:\n    pass\n", fake_chat,
    )

    assert result_path == test_path
    assert code == "def test_x():\n    assert True\n"
    assert reason is None


def test_generate_tests_for_skill_reports_a_reason_when_parsing_fails():
    result_path, code, reason = generate_tests_for_skill(
        "generated_gap", "GapSkill", "class GapSkill:\n    pass\n",
        lambda system_prompt, user_prompt: "not a valid response",
    )
    assert code is None
    assert reason is not None


def test_generate_tests_for_skill_handles_a_none_response():
    result_path, code, reason = generate_tests_for_skill(
        "generated_gap", "GapSkill", "class GapSkill:\n    pass\n",
        lambda system_prompt, user_prompt: None,
    )
    assert code is None
    assert reason is not None
