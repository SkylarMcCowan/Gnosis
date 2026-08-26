"""Regression tests for /cron (webagent.py:4026-4185). Always combined with
no_real_crontab, which fakes _read_crontab/_write_crontab in-memory - these
tests must never touch the machine's actual system crontab.
"""
import webagent


def test_cron_add_creates_a_task(isolated_data_dir, no_real_crontab):
    task_id, error = webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "news", description="Morning news")
    assert error is None
    assert task_id is not None

    tasks = webagent._load_cron_tasks()
    assert tasks[task_id]["action_type"] == "feature"
    assert tasks[task_id]["action_payload"] == "news"
    assert f"gnosis:{task_id}" in no_real_crontab["text"]


def test_cron_add_rejects_malformed_schedule(isolated_data_dir, no_real_crontab):
    task_id, error = webagent.cron_add(["not-a-field"], "feature", "news")
    assert task_id is None
    assert error is not None


def test_cron_add_rejects_unknown_feature(isolated_data_dir, no_real_crontab):
    task_id, error = webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "not_a_real_feature")
    assert task_id is None
    assert "Unknown feature" in error


def test_save_cron_tasks_returns_true_on_a_real_write(isolated_data_dir):
    assert webagent._save_cron_tasks({"abc123": {"schedule": "0 9 * * *"}}) is True
    assert webagent._load_cron_tasks() == {"abc123": {"schedule": "0 9 * * *"}}


def test_save_cron_tasks_returns_false_and_warns_on_failure(isolated_data_dir, monkeypatch, capsys):
    """Real, reported gap: a failed metadata write used to be a bare
    except OSError: pass - a real crontab entry could exist with no
    matching Gnosis record and nothing would say so."""
    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(webagent, "open", _raise, raising=False)
    result = webagent._save_cron_tasks({"abc123": {"schedule": "0 9 * * *"}})

    assert result is False
    assert "Failed to save cron task metadata" in capsys.readouterr().out


def test_cron_edit_updates_schedule_in_place(isolated_data_dir, no_real_crontab):
    task_id, _ = webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "news")
    ok, error = webagent.cron_edit(task_id, schedule_fields=["30", "10", "*", "*", "*"])
    assert ok is True
    assert error is None

    tasks = webagent._load_cron_tasks()
    assert tasks[task_id]["schedule"] == "30 10 * * *"


def test_cron_remove_deletes_task(isolated_data_dir, no_real_crontab):
    task_id, _ = webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "news")
    entries, _ = webagent.cron_list_entries()
    assert len(entries) == 1

    ok, entry_or_error = webagent.cron_remove(1)
    assert ok is True
    assert webagent._load_cron_tasks() == {}


def test_run_cron_task_now_executes_a_feature_task(isolated_data_dir, no_real_crontab, monkeypatch):
    monkeypatch.setattr(webagent, "news_command", lambda: [{"title": "fake headline"}])
    task_id, _ = webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "news")

    success, output = webagent.run_cron_task_now(task_id)
    assert success is True
    assert "fake headline" in output


def test_parse_alarm_time_relative_duration():
    fields, one_shot, error = webagent.parse_alarm_time("in 12 minutes")
    assert error is None
    assert one_shot is True
    assert len(fields) == 5


def test_parse_alarm_time_rejects_empty_description():
    fields, one_shot, error = webagent.parse_alarm_time("")
    assert fields is None
    assert error is not None
