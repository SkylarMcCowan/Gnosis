"""Regression tests for builder/code_generator.py - parse_file_block,
slug_for_gap, and generate_skill_for_gap, all with a fake coding_chat_fn
(no real model calls).
"""
from builder.code_generator import generate_skill_for_gap, parse_file_block, slug_for_gap


def test_parse_file_block_extracts_the_matching_block_and_skips_the_language_tag():
    raw = "### foo.py\n```python\nx = 1\n```\n"
    assert parse_file_block(raw, "foo.py") == "x = 1\n"


def test_parse_file_block_handles_a_bare_fence_with_no_language_tag():
    raw = "### foo.py\n```\nx = 1\n```\n"
    assert parse_file_block(raw, "foo.py") == "\nx = 1\n"


def test_parse_file_block_returns_none_for_a_missing_header():
    assert parse_file_block("no header here", "foo.py") is None


def test_parse_file_block_returns_none_for_the_wrong_path():
    raw = "### bar.py\n```python\nx = 1\n```\n"
    assert parse_file_block(raw, "foo.py") is None


def test_parse_file_block_returns_none_for_empty_input():
    assert parse_file_block("", "foo.py") is None
    assert parse_file_block(None, "foo.py") is None


def test_slug_for_gap_lowercases_and_replaces_punctuation():
    assert slug_for_gap("Test.run keeps failing!") == "test_run_keeps_failing"


def test_slug_for_gap_truncates_long_descriptions():
    long_description = "word " * 20
    assert len(slug_for_gap(long_description)) <= 40


def test_slug_for_gap_falls_back_when_nothing_alphanumeric_survives():
    assert slug_for_gap("!!!") == "gap"


def test_generate_skill_for_gap_returns_the_parsed_code():
    finding = {"pattern": "stage_failure", "tool": "test.run", "count": 3, "summary": "test.run keeps failing"}
    module_name = "generated_test_run_keeps_failing"
    fake_code = f"### {module_name}.py\n```python\nclass TestRunKeepsFailingSkill:\n    pass\n```\n"

    def fake_chat(system_prompt, user_prompt):
        assert "test.run keeps failing" in user_prompt
        assert "web.search: search the web" in system_prompt
        return fake_code

    result_module, class_name, code, reason = generate_skill_for_gap(
        finding, fake_chat, available_tools=[("web.search", "search the web")],
    )

    assert result_module == module_name
    assert class_name == "TestRunKeepsFailingSkill"
    assert code == "class TestRunKeepsFailingSkill:\n    pass\n"
    assert reason is None


def test_generate_skill_for_gap_reports_a_reason_when_parsing_fails():
    finding = {"summary": "something went wrong"}
    module_name, class_name, code, reason = generate_skill_for_gap(
        finding, lambda system_prompt, user_prompt: "not a valid response", available_tools=[],
    )
    assert code is None
    assert reason is not None


def test_generate_skill_for_gap_handles_a_none_response():
    finding = {"summary": "something went wrong"}
    module_name, class_name, code, reason = generate_skill_for_gap(
        finding, lambda system_prompt, user_prompt: None, available_tools=[],
    )
    assert code is None
    assert reason is not None
