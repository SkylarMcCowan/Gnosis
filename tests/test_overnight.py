"""Regression tests for Phase 16's overnight cycle (run_overnight_cycle) -
sequences the two real pipelines that already exist (self-improve, tool
generation) and writes one combined report. Same isolation discipline as
test_selfimprove.py: a disposable git repo, a fake _selfimprove_coding_chat,
never the real Gnosis checkout or a real model call.
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
def overnight_repo(tmp_path, monkeypatch):
    (tmp_path / "target.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / ".gitignore").write_text(
        "experience/\ngnosis_workspace/\nknowledge_base/\nactivity/\n"
    )
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "add", "-A")
    _run_git(tmp_path, "commit", "-q", "-m", "initial")
    monkeypatch.setattr(core_config, "_root_override", str(tmp_path))
    return tmp_path


def test_overnight_cycle_runs_both_pipelines_and_writes_a_combined_report(overnight_repo, monkeypatch):
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", lambda system_prompt, user_prompt: None)

    report = webagent.run_overnight_cycle()

    assert "GOOD MORNING" in report
    assert "Overnight Learning Run #1" in report
    assert "Self-improve:" in report
    assert "Tool generation:" in report
    assert "No change made" in report  # self-improve: no candidate, from the fake chat's None
    assert "No recurring capability gap found" in report  # tool-gen: no findings yet
    assert "relaunch `python3 webagent.py`" in report

    reports_dir = overnight_repo / "knowledge_base" / "overnight_reports"
    saved = list(reports_dir.glob("overnight_0001_*.md"))
    assert len(saved) == 1
    assert saved[0].read_text() == report


def test_overnight_cycle_run_numbers_increment_across_calls(overnight_repo, monkeypatch):
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", lambda system_prompt, user_prompt: None)

    webagent.run_overnight_cycle()
    second_report = webagent.run_overnight_cycle()

    assert "Overnight Learning Run #2" in second_report


def test_overnight_cycle_records_experiences_for_both_pipelines(overnight_repo, monkeypatch):
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", lambda system_prompt, user_prompt: None)

    webagent.run_overnight_cycle()

    experiences = load_experiences()
    agents = {e["agent"] for e in experiences}
    assert "self-improve" in agents
    assert "tool-generator" in agents


def test_overnight_feature_action_is_registered_and_dispatches():
    assert "overnight" in webagent.CRON_FEATURE_ACTIONS


def test_execute_cron_task_dispatches_the_overnight_feature(overnight_repo, monkeypatch):
    monkeypatch.setattr(webagent, "_selfimprove_coding_chat", lambda system_prompt, user_prompt: None)

    success, output = webagent._execute_cron_task({"action_type": "feature", "action_payload": "overnight"})

    assert success is True
    assert "GOOD MORNING" in output


def test_cmd_overnight_dispatches(monkeypatch, isolated_data_dir, capsys):
    calls = []
    monkeypatch.setattr(webagent, "run_overnight_cycle", lambda: calls.append(True) or "a report")
    webagent._cmd_overnight("/overnight")
    assert calls == [True]
    assert "a report" in capsys.readouterr().out
