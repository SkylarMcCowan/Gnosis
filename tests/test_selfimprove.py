"""Regression tests for /selfimprove (run_self_improve_cycle, webagent.py:3015-3111).

This is the highest-risk code path in the project - it reads real files,
asks a model to rewrite one of them, writes the result back, compiles it,
runs the test suite, and reverts on any failure. Every test here runs
against a disposable git repo in tmp_path (via overriding
core.config.project_root(), the same seam isolated_data_dir uses) so nothing
ever touches the real Gnosis repository, and every model call goes through a
fake _selfimprove_coding_chat so no network/Ollama call happens either.
"""
import os
import subprocess

import pytest

import webagent
from core import config as core_config
from memory.experience import load_experiences

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Gnosis Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Gnosis Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _run_git(repo_dir, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo_dir, capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


@pytest.fixture
def selfimprove_repo(tmp_path, monkeypatch):
    (tmp_path / "target.py").write_text("def add(a, b):\n    return a - b\n")
    # Mirrors the real repo's .gitignore: experience/ (Phase 5's log, written
    # on every run_self_improve_cycle() call) and gnosis_workspace/ (Phase
    # 10's sandbox worktrees) must never register as a dirty path, or a
    # second real run would refuse to proceed because the first run's own
    # write - or an orphaned workspace left behind by a hard crash mid-run,
    # since normal cleanup happens in a finally block but can't survive
    # e.g. the process being killed - looks like an uncommitted change.
    # knowledge_base/ is where _write_selfimprove_report's own report files
    # land (knowledge_base/selfimprove_reports/) - already gitignored in the
    # real repo; missing it here was a real gap this fixture had, caught by
    # the dry-run test below actually asserting a clean `git status`.
    # activity/ is Phase 12's event activity log (core/activity_log.py),
    # written on every published event (e.g. TEST_PASSED/TEST_FAILED from
    # a self-improve run) - same class of gap, caught the same way.
    (tmp_path / ".gitignore").write_text("experience/\ngnosis_workspace/\nknowledge_base/\nactivity/\n")
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "add", "-A")
    _run_git(tmp_path, "commit", "-q", "-m", "initial")
    monkeypatch.setattr(core_config, "_root_override", str(tmp_path))
    return tmp_path


def _fake_coding_chat(candidate=None, fix=None, test=None, security=None, performance=None, documentation=None):
    """Stand-in for _selfimprove_coding_chat, routed by which stage's
    system prompt is asking (candidate selection vs. file fix vs. test gen
    vs. Phase 11's review panel) - all six stages share that one function
    in the real code. Reviewer responses default to a plain [OK] so tests
    that don't care about the review panel don't have to think about it."""
    def _fake(system_prompt, user_prompt):
        if "propose exactly ONE" in system_prompt:
            return candidate
        if "COMPLETE new content" in system_prompt:
            return fix
        if "writing a Python unittest test" in system_prompt:
            return test
        if "Security Reviewer" in system_prompt:
            return security or "[OK] No security concerns found."
        if "Performance Reviewer" in system_prompt:
            return performance or "[OK] No performance concerns found."
        if "Documentation Reviewer" in system_prompt:
            return documentation or "[OK] Clear enough to review as-is."
        return None
    return _fake


def test_blocked_on_dirty_worktree(selfimprove_repo):
    (selfimprove_repo / "scratch.txt").write_text("uncommitted")

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "Skipped" in report
    assert "scratch.txt" in report
    # Nothing should have been touched.
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a - b\n"
    # A blocked cycle never attempted a fix - success is None, not False.
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is None


def test_an_orphaned_workspace_from_a_crashed_run_does_not_block_the_next_run(selfimprove_repo, monkeypatch):
    """Regression for the same class of bug the experience/ .gitignore gap
    was: normal cleanup happens in a `finally` block, but that can't run if
    the process is killed mid-cycle, so a real crash can leave
    gnosis_workspace/runs/<id>/ behind. It must not then look like an
    uncommitted change and block every future run."""
    orphaned = selfimprove_repo / "gnosis_workspace" / "runs" / "orphaned-id"
    orphaned.mkdir(parents=True)
    (orphaned / "leftover.txt").write_text("from a run that never cleaned up")
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", _fake_coding_chat())

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "Skipped" not in report  # must not be treated as a dirty worktree
    assert "No change made" in report  # the actual (unrelated) "no candidate" outcome


def test_skips_a_candidate_that_has_failed_repeatedly(selfimprove_repo, monkeypatch):
    """Phase 7's planner: run_self_improve_cycle must not just re-propose
    the same goal forever once it's already failed repeatedly."""
    from memory.experience import build_experience, record_experience

    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", _fake_coding_chat(candidate=candidate))
    goal = "Fix target.py: add() subtracts instead of adding"
    record_experience(build_experience(goal=goal, success=False, agent="self-improve"))
    record_experience(build_experience(goal=goal, success=False, agent="self-improve"))

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "failed repeatedly" in report
    # Nothing touched - the stuck goal was never actually attempted.
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a - b\n"
    experiences = load_experiences()
    assert len(experiences) == 3  # the 2 seeded + this cycle's skip
    assert experiences[-1]["success"] is None


def test_no_candidate_when_model_returns_nothing(selfimprove_repo, monkeypatch):
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", _fake_coding_chat())

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "No change made" in report
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is None
    assert experiences[0]["tools_used"] == ["repo.audit"]


def test_no_candidate_when_target_is_denylisted(selfimprove_repo, monkeypatch):
    candidate = '{"target_file": "webagent.py", "issue": "x", "proposed_fix_summary": "y"}'
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", _fake_coding_chat(candidate=candidate))

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "denylist" in report


def test_applies_a_real_fix_that_passes_its_own_test(selfimprove_repo, monkeypatch):
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat",
        _fake_coding_chat(candidate=candidate, fix=fix, test=test),
    )

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "applied" in report.lower()
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert (selfimprove_repo / "tests" / "test_target.py").exists()
    # Left staged for human review - never committed automatically.
    status = _run_git(selfimprove_repo, "status", "--porcelain")
    assert "target.py" in status.stdout
    log = _run_git(selfimprove_repo, "log", "--oneline")
    assert len(log.stdout.strip().splitlines()) == 1
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is True
    assert experiences[0]["score"] == 1.0
    assert experiences[0]["plan"] == "use + instead of -"
    assert experiences[0]["tools_used"] == ["repo.audit", "test.run"]
    assert "Succeeded" in experiences[0]["lessons"][0]
    # The sandbox workspace used to build and verify the fix leaves nothing behind.
    runs_dir = selfimprove_repo / "gnosis_workspace" / "runs"
    assert not runs_dir.exists() or os.listdir(runs_dir) == []


def test_applied_report_includes_the_engineering_team_review(selfimprove_repo, monkeypatch):
    """Phase 11: a real diff a human is about to look at gets a real
    review panel appended - informational only, doesn't change that the
    fix was applied."""
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat",
        _fake_coding_chat(
            candidate=candidate, fix=fix, test=test,
            security="[Concern] Looks fine, but flagging for the test.",
        ),
    )

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "Engineering team review" in report
    assert "Security: [Concern] Looks fine, but flagging for the test." in report
    assert "Performance: [OK]" in report
    assert "Documentation: [OK]" in report
    assert "Release Manager: Review carefully before applying" in report


def test_dry_run_report_includes_the_engineering_team_review(selfimprove_repo, monkeypatch):
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat", _fake_coding_chat(candidate=candidate, fix=fix, test=test),
    )

    success, report = webagent.run_self_improve_cycle(dry_run=True)

    assert success is True
    assert "Engineering team review" in report
    assert "Release Manager: Looks reasonable" in report


def test_dry_run_verifies_the_fix_but_never_touches_the_live_repo(selfimprove_repo, monkeypatch):
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat",
        _fake_coding_chat(candidate=candidate, fix=fix, test=test),
    )

    success, report = webagent.run_self_improve_cycle(dry_run=True)

    assert success is True
    assert "dry run" in report.lower()
    assert "-    return a - b" in report  # the verified diff is in the report
    assert "+    return a + b" in report
    # Nothing landed in the live repo at all - not even staged.
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a - b\n"
    assert not (selfimprove_repo / "tests" / "test_target.py").exists()
    status = _run_git(selfimprove_repo, "status", "--porcelain")
    assert status.stdout.strip() == ""
    # The dry run still fully verified the fix - that's a real, recorded success.
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is True
    runs_dir = selfimprove_repo / "gnosis_workspace" / "runs"
    assert not runs_dir.exists() or os.listdir(runs_dir) == []


def test_dry_run_still_reverts_and_reports_on_a_failing_generated_test(selfimprove_repo, monkeypatch):
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 999)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat",
        _fake_coding_chat(candidate=candidate, fix=fix, test=test),
    )

    success, report = webagent.run_self_improve_cycle(dry_run=True)

    assert success is True
    assert "reverted" in report.lower()  # a dry run that fails verification reports the same as a real one
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_reverts_a_fix_whose_own_generated_test_fails(selfimprove_repo, monkeypatch):
    candidate = (
        '{"target_file": "target.py", "issue": "add() subtracts instead of adding", '
        '"proposed_fix_summary": "use + instead of -"}'
    )
    fix = "### target.py\n```python\ndef add(a, b):\n    return a + b\n```\n"
    # Deliberately wrong expected value, so the generated test itself fails.
    test = (
        "### tests/test_target.py\n```python\nimport unittest\nfrom target import add\n\n"
        "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 999)\n```\n"
    )
    monkeypatch.setattr(
        webagent, "_selfimprove_coding_chat",
        _fake_coding_chat(candidate=candidate, fix=fix, test=test),
    )

    success, report = webagent.run_self_improve_cycle()

    assert success is True
    assert "reverted" in report.lower()
    assert (selfimprove_repo / "target.py").read_text() == "def add(a, b):\n    return a - b\n"
    assert not (selfimprove_repo / "tests" / "test_target.py").exists()
    experiences = load_experiences()
    assert len(experiences) == 1
    assert experiences[0]["success"] is False
    # Nothing ever touched the live repo in the first place - the failed
    # attempt only ever existed inside the (now-destroyed) sandbox workspace.
    runs_dir = selfimprove_repo / "gnosis_workspace" / "runs"
    assert not runs_dir.exists() or os.listdir(runs_dir) == []
    assert experiences[0]["score"] == 0.0
    assert experiences[0]["tools_used"] == ["repo.audit", "test.run", "git.diff"]
    assert "Failed" in experiences[0]["lessons"][0]


def test_audit_repository_reports_basic_stats(isolated_data_dir):
    (isolated_data_dir / "a.py").write_text("# TODO: fix this\nx = 1\n")
    (isolated_data_dir / "tests").mkdir()

    report = webagent.audit_repository()

    assert "Total files: 1" in report
    assert "Tests folder present: Yes" in report
    assert "a.py:1: # TODO: fix this" in report


def test_audit_repository_advanced_reports_no_readme_no_ci_no_docs(isolated_data_dir):
    report = webagent.audit_repository_advanced()

    assert "No README found." in report
    assert "No CI configuration found." in report
    assert "No docs/ directory found." in report
    assert "0 test file(s) found for 0 non-test .py file(s)" in report


def test_audit_repository_advanced_flags_a_thin_readme(isolated_data_dir):
    (isolated_data_dir / "README.md").write_text("Just a title.\n")

    report = webagent.audit_repository_advanced()

    assert "thin, consider expanding" in report


def test_audit_repository_advanced_recognizes_a_substantial_readme(isolated_data_dir):
    (isolated_data_dir / "README.md").write_text(("word " * 150) + "\n## Installation\n## Usage\n")

    report = webagent.audit_repository_advanced()

    assert "sections found: install, usage" in report
    assert "thin" not in report


def test_audit_repository_advanced_counts_test_files(isolated_data_dir):
    (isolated_data_dir / "a.py").write_text("x = 1\n")
    (isolated_data_dir / "test_a.py").write_text("def test_x(): pass\n")

    report = webagent.audit_repository_advanced()

    assert "1 test file(s) found for 1 non-test .py file(s)" in report


def test_audit_repository_advanced_detects_github_actions_ci(isolated_data_dir):
    workflows = isolated_data_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\n")

    report = webagent.audit_repository_advanced()

    assert "GitHub Actions (1 workflow file(s))" in report


def test_audit_repository_advanced_reports_docs_health_and_empty_files(isolated_data_dir):
    docs = isolated_data_dir / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("Some real content.\n")
    (docs / "stale.md").write_text("")

    report = webagent.audit_repository_advanced()

    assert "2 doc file(s) in docs/" in report
    assert "1 empty: stale.md" in report
