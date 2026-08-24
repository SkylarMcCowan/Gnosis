"""Regression tests for governance/permissions.py's execute_as_autonomous -
the one real mechanism Phase 15 built. Uses the real, shared tool_registry
(this module doesn't take one injected, by design - see its own
docstring), so every cron test here uses the same isolated_data_dir +
no_real_crontab protection established for every other cron test in this
suite - never the real system crontab.
"""
import pytest

from core.activity_log import load_activity
from governance.permissions import execute_as_autonomous
from tools.base import Permission, Tool
from tools.registry import registry as tool_registry


class _FakeForbiddenTool(Tool):
    name = "test.forbidden"
    description = "A fake FORBIDDEN tool, registered only for this test."
    parameters = {}
    permission = Permission.FORBIDDEN

    def execute(self, **kwargs):
        return "should never run"


@pytest.fixture
def forbidden_tool():
    tool = _FakeForbiddenTool()
    tool_registry.register(tool)
    yield tool
    tool_registry.unregister(tool.name)


def test_execute_as_autonomous_raises_for_an_unknown_tool():
    with pytest.raises(KeyError):
        execute_as_autonomous("nonexistent.tool")


def test_execute_as_autonomous_refuses_a_forbidden_tool(isolated_data_dir, forbidden_tool):
    with pytest.raises(PermissionError, match="FORBIDDEN"):
        execute_as_autonomous("test.forbidden")

    entries = load_activity(event_name="AUTONOMOUS_ACTION")
    assert len(entries) == 1
    assert entries[0]["tool"] == "test.forbidden"
    assert entries[0]["allowed"] is False


def test_execute_as_autonomous_allows_a_safe_tool_and_logs_it(isolated_data_dir):
    (isolated_data_dir / "a.py").write_text("x = 1\n")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=isolated_data_dir)
    subprocess.run(["git", "add", "-A"], cwd=isolated_data_dir)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=isolated_data_dir,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"},
    )

    result = execute_as_autonomous("repo.audit")

    assert "Total files" in result
    entries = load_activity(event_name="AUTONOMOUS_ACTION")
    assert len(entries) == 1
    assert entries[0]["tool"] == "repo.audit"
    assert entries[0]["permission"] == Permission.SAFE
    assert entries[0]["allowed"] is True


def test_execute_as_autonomous_allows_a_requires_approval_tool_and_logs_it(isolated_data_dir, no_real_crontab):
    task_id, error = execute_as_autonomous(
        "cron.add", agent="test-agent", schedule_fields=["0", "9", "*", "*", "*"],
        action_type="prompt", action_payload="a reminder",
    )

    assert error is None
    assert task_id
    assert f"gnosis:{task_id}" in no_real_crontab["text"]  # the real cron_add ran, against the fake crontab only
    entries = load_activity(event_name="AUTONOMOUS_ACTION")
    assert len(entries) == 1
    assert entries[0]["tool"] == "cron.add"
    assert entries[0]["permission"] == Permission.REQUIRES_APPROVAL
    assert entries[0]["allowed"] is True
    assert entries[0]["agent"] == "test-agent"


def test_execute_as_autonomous_passes_through_a_tool_execution_error(isolated_data_dir):
    with pytest.raises(TypeError):
        execute_as_autonomous("fs.read")  # missing required args
