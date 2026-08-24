"""Regression tests for tools/scheduler/*.py (cron.list/add/edit/remove/run).

These are all Tool classes in isolation, constructed with a fake callable -
proving they forward arguments correctly, not that the real cron_* functions
work (Phase 0's test_cron.py already covers that against a faked crontab).
Real wiring against webagent's actual cron functions is in
tests/test_tools_wiring.py, still never touching the real system crontab.
"""
from tools.base import Permission
from tools.scheduler.add import CronAddTool
from tools.scheduler.edit import CronEditTool
from tools.scheduler.list import CronListTool
from tools.scheduler.remove import CronRemoveTool
from tools.scheduler.run import CronRunTool


def test_cron_list_forwards_no_args():
    calls = []
    tool = CronListTool(lambda: calls.append(True) or ([], None))
    assert tool.execute() == ([], None)
    assert calls == [True]


def test_cron_list_metadata():
    tool = CronListTool(lambda: ([], None))
    assert tool.name == "cron.list"
    assert tool.permission == Permission.SAFE


def test_cron_add_forwards_all_arguments():
    calls = []

    def fake_add(schedule_fields, action_type, action_payload, description=None, one_shot=False):
        calls.append((schedule_fields, action_type, action_payload, description, one_shot))
        return ("abc123", None)

    tool = CronAddTool(fake_add)
    result = tool.execute(["0", "9", "*", "*", "*"], "feature", "news", description="Morning news")

    assert result == ("abc123", None)
    assert calls == [(["0", "9", "*", "*", "*"], "feature", "news", "Morning news", False)]


def test_cron_add_metadata():
    tool = CronAddTool(lambda *a, **k: (None, "err"))
    assert tool.name == "cron.add"
    assert tool.permission == Permission.REQUIRES_APPROVAL


def test_cron_edit_forwards_all_arguments():
    calls = []

    def fake_edit(task_id, schedule_fields=None, action_type=None, action_payload=None, description=None, one_shot=None):
        calls.append((task_id, schedule_fields, action_type, action_payload, description, one_shot))
        return (True, None)

    tool = CronEditTool(fake_edit)
    result = tool.execute("abc123", schedule_fields=["30", "10", "*", "*", "*"])

    assert result == (True, None)
    assert calls == [("abc123", ["30", "10", "*", "*", "*"], None, None, None, None)]


def test_cron_edit_metadata():
    tool = CronEditTool(lambda *a, **k: (True, None))
    assert tool.name == "cron.edit"
    assert tool.permission == Permission.REQUIRES_APPROVAL


def test_cron_remove_forwards_index():
    calls = []
    tool = CronRemoveTool(lambda index: calls.append(index) or (True, {}))
    assert tool.execute(index=1) == (True, {})
    assert calls == [1]


def test_cron_remove_metadata():
    tool = CronRemoveTool(lambda index: (True, {}))
    assert tool.name == "cron.remove"
    assert tool.permission == Permission.REQUIRES_APPROVAL


def test_cron_run_forwards_task_id():
    calls = []
    tool = CronRunTool(lambda task_id: calls.append(task_id) or (True, "ok"))
    assert tool.execute(task_id="abc123") == (True, "ok")
    assert calls == ["abc123"]


def test_cron_run_metadata():
    tool = CronRunTool(lambda task_id: (True, "ok"))
    assert tool.name == "cron.run"
    assert tool.permission == Permission.RESTRICTED
