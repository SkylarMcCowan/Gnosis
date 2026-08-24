"""Regression tests for builder/proposals.py - write_proposal never
registers anything, only ever writes files under isolated_data_dir's
gnosis_workspace/proposals/.
"""
from builder.proposals import write_proposal


def test_write_proposal_writes_the_skill_and_test_files(isolated_data_dir):
    proposal_id = write_proposal(
        {"summary": "test.run keeps failing"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
    )

    proposal_dir = isolated_data_dir / "gnosis_workspace" / "proposals" / proposal_id
    assert (proposal_dir / "generated_gap.py").read_text() == "class GapSkill:\n    pass\n"
    assert (proposal_dir / "test_gap.py").read_text() == "def test_x(): pass\n"


def test_write_proposal_includes_the_review_panel_when_given(isolated_data_dir):
    proposal_id = write_proposal(
        {"summary": "gap"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
        reviews={"security": "[OK] fine", "performance": "[Minor] a nit", "documentation": "[OK] clear"},
        recommendation="Looks reasonable - no reviewer flagged a concern and tests passed.",
    )
    report = (isolated_data_dir / "gnosis_workspace" / "proposals" / proposal_id / "report.md").read_text()
    assert "Engineering team review" in report
    assert "[OK] fine" in report
    assert "[Minor] a nit" in report
    assert "Looks reasonable" in report


def test_write_proposal_omits_the_review_section_when_not_given(isolated_data_dir):
    proposal_id = write_proposal(
        {"summary": "gap"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
    )
    report = (isolated_data_dir / "gnosis_workspace" / "proposals" / proposal_id / "report.md").read_text()
    assert "Engineering team review" not in report


def test_write_proposal_report_reflects_a_pass(isolated_data_dir):
    proposal_id = write_proposal(
        {"summary": "test.run keeps failing"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
    )
    report = (isolated_data_dir / "gnosis_workspace" / "proposals" / proposal_id / "report.md").read_text()
    assert "PASSED" in report
    assert "test.run keeps failing" in report
    assert "GapSkill" in report


def test_write_proposal_report_reflects_a_failure(isolated_data_dir):
    proposal_id = write_proposal(
        {"summary": "test.run keeps failing"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        False, "1 failed - AssertionError",
    )
    report = (isolated_data_dir / "gnosis_workspace" / "proposals" / proposal_id / "report.md").read_text()
    assert "FAILED" in report
    assert "AssertionError" in report


def test_write_proposal_handles_a_string_gap_finding(isolated_data_dir):
    proposal_id = write_proposal(
        "a plain string gap description", "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
    )
    assert proposal_id  # did not raise on a non-dict finding


def test_write_proposal_never_registers_anything(isolated_data_dir):
    from tools.registry import registry as tool_registry
    from skills.registry import registry as skill_registry
    before_tools = set(tool_registry.list())
    before_skills = set(skill_registry.list())

    write_proposal(
        {"summary": "gap"}, "generated_gap", "GapSkill",
        "class GapSkill:\n    pass\n", "tests/test_gap.py", "def test_x(): pass\n",
        True, "1 passed",
    )

    assert set(tool_registry.list()) == before_tools
    assert set(skill_registry.list()) == before_skills
