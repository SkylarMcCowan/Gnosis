"""Tests for worklog.py's pure-Python storage/reporting layer (Work Tracker
pane) - no Qt involved, same split as games/idle_island.py's economy
functions. core.config._root_override is redirected to a scratch dir by the
autouse isolated_data_dir fixture in conftest.py, so these never touch the
project's real worklog/ directory.
"""
from datetime import date, datetime, timedelta

import pytest

import worklog


def test_load_data_on_missing_file_does_not_create_directory(tmp_path):
    assert worklog.list_projects() == []
    assert not (tmp_path / "worklog").exists()


def test_add_project_then_list_and_get():
    record = worklog.add_project("Client Site Rebuild", "SITE-01", "Rebuilding the marketing site.")
    assert record["code"] == "SITE-01"
    assert worklog.list_projects() == [record]
    assert worklog.get_project("SITE-01") == record
    assert worklog.get_project("NOPE") is None


def test_add_project_requires_name_and_code():
    with pytest.raises(ValueError):
        worklog.add_project("", "CODE")
    with pytest.raises(ValueError):
        worklog.add_project("Name", "")


def test_add_project_rejects_duplicate_code_case_insensitively():
    worklog.add_project("First", "ABC")
    with pytest.raises(ValueError):
        worklog.add_project("Second", "abc")


def test_duplicate_project_gets_a_fresh_unique_code():
    worklog.add_project("Original", "ORIG", "desc")
    copy1 = worklog.duplicate_project("ORIG")
    assert copy1["code"] == "ORIG-COPY"
    assert copy1["name"] == "Original (Copy)"
    assert copy1["description"] == "desc"

    copy2 = worklog.duplicate_project("ORIG")
    assert copy2["code"] == "ORIG-COPY2"

    assert {p["code"] for p in worklog.list_projects()} == {"ORIG", "ORIG-COPY", "ORIG-COPY2"}


def test_delete_project_returns_false_when_not_found():
    assert worklog.delete_project("MISSING") is False


def test_delete_project_removes_it():
    worklog.add_project("Doomed", "DOOM")
    assert worklog.delete_project("DOOM") is True
    assert worklog.get_project("DOOM") is None


def test_add_task_requires_an_existing_project():
    with pytest.raises(ValueError):
        worklog.add_task("Do a thing", "NOPE")


def test_add_task_starts_in_new_status_with_one_history_entry():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Write the report", "P1", hours=2.5)
    assert task["status"] == "New"
    assert task["hours"] == 2.5
    assert len(task["status_history"]) == 1
    assert task["status_history"][0]["status"] == "New"


def test_move_task_status_slides_forward_and_stamps_history():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Ship it", "P1")

    updated = worklog.move_task_status(task["id"], 1)
    assert updated["status"] == "Working"
    assert [e["status"] for e in updated["status_history"]] == ["New", "Working"]
    assert "at" in updated["status_history"][-1]


def test_move_task_status_clamps_at_either_end():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Edge case", "P1")

    back = worklog.move_task_status(task["id"], -1)
    assert back["status"] == "New"
    assert len(back["status_history"]) == 1  # no-op, no extra history entry

    for _ in range(len(worklog.STATUSES) + 2):
        worklog.move_task_status(task["id"], 1)
    assert worklog.list_tasks()[0]["status"] == worklog.STATUSES[-1]


def test_set_task_hours_updates_value():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Bill some hours", "P1")
    worklog.set_task_hours(task["id"], 4.25)
    assert worklog.list_tasks()[0]["hours"] == 4.25


def test_add_task_note_requires_text():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Do a thing", "P1")
    with pytest.raises(ValueError):
        worklog.add_task_note(task["id"], "   ")


def test_add_task_note_requires_an_existing_task():
    with pytest.raises(ValueError):
        worklog.add_task_note("missing-id", "note")


def test_add_task_note_is_append_only_and_never_overwrites_history():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Do a thing", "P1")
    worklog.add_task_note(task["id"], "first note")
    worklog.add_task_note(task["id"], "second note")

    notes = worklog.list_task_notes(task["id"])
    assert [n["text"] for n in notes] == ["first note", "second note"]
    assert all("id" in n and "at" in n for n in notes)

    # unrelated edits to the task (status, hours) leave prior notes untouched
    worklog.move_task_status(task["id"], 1)
    worklog.set_task_hours(task["id"], 3.0)
    assert [n["text"] for n in worklog.list_task_notes(task["id"])] == ["first note", "second note"]


def test_set_task_title_updates_value():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Original title", "P1")
    worklog.set_task_title(task["id"], "Corrected title")
    assert worklog.list_tasks()[0]["title"] == "Corrected title"


def test_set_task_title_rejects_blank_title():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Original title", "P1")
    with pytest.raises(ValueError):
        worklog.set_task_title(task["id"], "   ")
    assert worklog.list_tasks()[0]["title"] == "Original title"


def test_set_task_project_code_requires_an_existing_project():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Do a thing", "P1")
    with pytest.raises(ValueError):
        worklog.set_task_project_code(task["id"], "NOPE")


def test_set_task_project_code_reassigns_hours_in_past_reports_retroactively():
    worklog.add_project("Wrong", "WRONG")
    worklog.add_project("Right", "RIGHT")
    task = worklog.add_task("Billed to the wrong code", "WRONG", hours=5.0)
    for _ in range(4):  # New -> Working -> Hold -> Review -> Done
        worklog.move_task_status(task["id"], 1)

    today = date.today().isoformat()
    assert worklog.daily_summary(today)["by_project"] == {"WRONG": 5.0}

    worklog.set_task_project_code(task["id"], "RIGHT")

    # same completion date, no new status change - the existing report now
    # attributes the hours to the corrected code instead
    assert worklog.daily_summary(today)["by_project"] == {"RIGHT": 5.0}
    assert worklog.list_tasks()[0]["project_code"] == "RIGHT"


def test_task_activity_dates_and_tasks_active_on_date_track_status_changes():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Multi-day task", "P1")
    worklog.move_task_status(task["id"], 1)  # New -> Working, same day in these tests

    today = date.today().isoformat()
    activity = worklog.task_activity_dates()
    assert today in activity
    assert task["id"] in activity[today]

    active = worklog.tasks_active_on_date(today)
    assert len(active) == 1
    assert active[0]["task"]["id"] == task["id"]
    assert active[0]["statuses"] == ["New", "Working"]

    assert worklog.tasks_active_on_date("1999-01-01") == []


def test_delete_task_removes_it():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Temp", "P1")
    assert worklog.delete_task(task["id"]) is True
    assert worklog.list_tasks() == []
    assert worklog.delete_task(task["id"]) is False


def test_tasks_for_project_filters_by_code():
    worklog.add_project("A", "A1")
    worklog.add_project("B", "B1")
    worklog.add_task("Task A", "A1")
    worklog.add_task("Task B", "B1")
    assert [t["title"] for t in worklog.tasks_for_project("A1")] == ["Task A"]


def test_add_event_requires_title_and_date():
    with pytest.raises(ValueError):
        worklog.add_event("", "2026-08-26")
    with pytest.raises(ValueError):
        worklog.add_event("Standup", "")


def test_events_on_date_filters_correctly():
    worklog.add_event("Standup", "2026-08-26", "9:00 AM")
    worklog.add_event("Retro", "2026-08-27", "3:00 PM")
    events = worklog.events_on_date("2026-08-26")
    assert len(events) == 1
    assert events[0]["title"] == "Standup"


def test_delete_event_removes_it():
    event = worklog.add_event("One-off", "2026-08-26")
    assert worklog.delete_event(event["id"]) is True
    assert worklog.list_events() == []


def test_update_event_edits_fields_in_place():
    event = worklog.add_event("Standup", "2026-08-26", "9:00 AM", "Daily sync")
    updated = worklog.update_event(event["id"], "Standup (moved)", "2026-08-27", "10:00 AM", "Daily sync, later")
    assert updated["title"] == "Standup (moved)"
    assert updated["date"] == "2026-08-27"
    assert updated["time"] == "10:00 AM"
    assert updated["description"] == "Daily sync, later"
    assert worklog.list_events() == [updated]
    assert worklog.events_on_date("2026-08-26") == []
    assert worklog.events_on_date("2026-08-27") == [updated]


def test_update_event_requires_title_date_and_an_existing_event():
    event = worklog.add_event("Standup", "2026-08-26")
    with pytest.raises(ValueError):
        worklog.update_event(event["id"], "", "2026-08-26")
    with pytest.raises(ValueError):
        worklog.update_event(event["id"], "Standup", "")
    with pytest.raises(ValueError):
        worklog.update_event("missing-id", "Standup", "2026-08-26")


def test_add_event_accepts_an_optional_job_code():
    worklog.add_project("Proj", "P1")
    event = worklog.add_event("Site visit", "2026-08-26", project_code="P1")
    assert event["project_code"] == "P1"

    # blank is fine - a job code is optional, unlike on a task
    untagged = worklog.add_event("Personal reminder", "2026-08-26")
    assert untagged["project_code"] == ""


def test_add_event_rejects_an_unknown_job_code():
    with pytest.raises(ValueError):
        worklog.add_event("Site visit", "2026-08-26", project_code="NOPE")


def test_update_event_can_set_clear_or_reject_the_job_code():
    worklog.add_project("Proj", "P1")
    event = worklog.add_event("Site visit", "2026-08-26")
    assert event["project_code"] == ""

    tagged = worklog.update_event(event["id"], "Site visit", "2026-08-26", project_code="P1")
    assert tagged["project_code"] == "P1"

    cleared = worklog.update_event(event["id"], "Site visit", "2026-08-26", project_code="")
    assert cleared["project_code"] == ""

    with pytest.raises(ValueError):
        worklog.update_event(event["id"], "Site visit", "2026-08-26", project_code="NOPE")


def test_load_data_backfills_project_code_on_events_missing_it():
    # events created before the job-code field existed shouldn't KeyError
    event = worklog.add_event("Legacy event", "2026-08-26")
    data = worklog.load_data()
    del data["events"][0]["project_code"]
    worklog.save_data(data)

    reloaded = worklog.list_events()
    assert reloaded[0]["project_code"] == ""


def test_sync_recurring_events_tags_the_generated_calendar_event_with_the_rules_job_code():
    worklog.add_project("Proj", "P1")
    today = date.today()
    worklog.add_recurring_event("Weekly chore", today.weekday(), "P1")
    worklog.sync_recurring_events(today.isoformat())

    events = worklog.events_on_date(today.isoformat())
    assert len(events) == 1
    assert events[0]["project_code"] == "P1"


def test_add_recurring_event_requires_title_valid_weekday_and_existing_project():
    worklog.add_project("Proj", "P1")
    with pytest.raises(ValueError):
        worklog.add_recurring_event("", 0, "P1")
    with pytest.raises(ValueError):
        worklog.add_recurring_event("Chore", 7, "P1")
    with pytest.raises(ValueError):
        worklog.add_recurring_event("Chore", -1, "P1")
    with pytest.raises(ValueError):
        worklog.add_recurring_event("Chore", 0, "NOPE")


def test_set_recurring_event_active_requires_an_existing_rule():
    with pytest.raises(ValueError):
        worklog.set_recurring_event_active("missing-id", False)


def test_sync_recurring_events_generates_todays_occurrence_immediately():
    worklog.add_project("Proj", "P1")
    today = date.today()
    worklog.add_recurring_event("Take out trash", today.weekday(), "P1", hours=0.5)

    created = worklog.sync_recurring_events(today.isoformat())
    assert len(created) == 1
    assert created[0]["title"] == "Take out trash"
    assert created[0]["recurring_date"] == today.isoformat()
    assert created[0]["hours"] == 0.5
    assert created[0]["recurring_event_id"] == worklog.list_recurring_events()[0]["id"]

    events = worklog.events_on_date(today.isoformat())
    assert len(events) == 1
    assert events[0]["title"] == "Take out trash"

    # calling sync again the same day is a no-op, not a duplicate
    assert worklog.sync_recurring_events(today.isoformat()) == []
    assert len(worklog.list_tasks()) == 1


def test_sync_recurring_events_waits_for_the_next_occurrence_if_not_today():
    worklog.add_project("Proj", "P1")
    today = date.today()
    tomorrow_weekday = (today.weekday() + 1) % 7
    worklog.add_recurring_event("Weekly chore", tomorrow_weekday, "P1")

    assert worklog.sync_recurring_events(today.isoformat()) == []
    assert worklog.list_tasks() == []

    tomorrow = today + timedelta(days=1)
    created = worklog.sync_recurring_events(tomorrow.isoformat())
    assert len(created) == 1
    assert created[0]["recurring_date"] == tomorrow.isoformat()


def test_sync_recurring_events_backfills_every_missed_week_without_dropping_any():
    worklog.add_project("Proj", "P1")
    today = date.today()
    worklog.add_recurring_event("Weekly chore", today.weekday(), "P1")
    worklog.sync_recurring_events(today.isoformat())
    assert len(worklog.list_tasks()) == 1

    three_weeks_later = today + timedelta(weeks=3)
    created = worklog.sync_recurring_events(three_weeks_later.isoformat())
    assert len(created) == 3
    expected_dates = {(today + timedelta(weeks=i)).isoformat() for i in (1, 2, 3)}
    assert {t["recurring_date"] for t in created} == expected_dates
    assert len(worklog.list_tasks()) == 4


def test_sync_recurring_events_skips_paused_rules():
    worklog.add_project("Proj", "P1")
    today = date.today()
    rule = worklog.add_recurring_event("Weekly chore", today.weekday(), "P1")
    worklog.set_recurring_event_active(rule["id"], False)

    assert worklog.sync_recurring_events(today.isoformat()) == []
    assert worklog.list_tasks() == []


def test_update_recurring_event_edits_fields_but_preserves_active_and_watermark():
    worklog.add_project("Proj", "P1")
    worklog.add_project("Other", "P2")
    today = date.today()
    rule = worklog.add_recurring_event("Weekly chore", today.weekday(), "P1", hours=1.0)
    worklog.sync_recurring_events(today.isoformat())  # sets last_generated_date, so it's not None below
    worklog.set_recurring_event_active(rule["id"], False)

    new_weekday = (today.weekday() + 2) % 7
    updated = worklog.update_recurring_event(
        rule["id"], "Renamed chore", new_weekday, "P2", 2.5, "5:00 PM", "New description",
    )
    assert updated["title"] == "Renamed chore"
    assert updated["weekday"] == new_weekday
    assert updated["project_code"] == "P2"
    assert updated["hours"] == 2.5
    assert updated["time"] == "5:00 PM"
    assert updated["description"] == "New description"
    # untouched by the edit
    assert updated["active"] is False
    assert updated["last_generated_date"] == today.isoformat()
    assert updated["id"] == rule["id"]


def test_update_recurring_event_requires_title_valid_weekday_existing_project_and_rule():
    worklog.add_project("Proj", "P1")
    rule = worklog.add_recurring_event("Weekly chore", 0, "P1")
    with pytest.raises(ValueError):
        worklog.update_recurring_event(rule["id"], "", 0, "P1")
    with pytest.raises(ValueError):
        worklog.update_recurring_event(rule["id"], "Chore", 7, "P1")
    with pytest.raises(ValueError):
        worklog.update_recurring_event(rule["id"], "Chore", 0, "NOPE")
    with pytest.raises(ValueError):
        worklog.update_recurring_event("missing-id", "Chore", 0, "P1")


def test_delete_recurring_event_removes_the_rule_but_keeps_generated_tasks():
    worklog.add_project("Proj", "P1")
    today = date.today()
    rule = worklog.add_recurring_event("Weekly chore", today.weekday(), "P1")
    worklog.sync_recurring_events(today.isoformat())
    assert len(worklog.list_tasks()) == 1

    assert worklog.delete_recurring_event("missing-id") is False
    assert worklog.delete_recurring_event(rule["id"]) is True
    assert worklog.list_recurring_events() == []
    assert len(worklog.list_tasks()) == 1


def test_log_task_hours_sets_and_clears_a_day():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Multi-day work", "P1")
    today = date.today().isoformat()

    worklog.log_task_hours(task["id"], today, 3.0)
    assert worklog.list_tasks()[0]["daily_hours"] == {today: 3.0}

    worklog.log_task_hours(task["id"], today, 1.5)  # edited in place, not appended
    assert worklog.list_tasks()[0]["daily_hours"] == {today: 1.5}

    worklog.log_task_hours(task["id"], today, 0)  # 0 clears the day's entry
    assert worklog.list_tasks()[0]["daily_hours"] == {}


def test_log_task_hours_rejects_negative_hours():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Work", "P1")
    with pytest.raises(ValueError):
        worklog.log_task_hours(task["id"], date.today().isoformat(), -1)


def test_log_task_hours_requires_an_existing_task():
    with pytest.raises(ValueError):
        worklog.log_task_hours("missing-id", date.today().isoformat(), 2.0)


def test_total_task_hours_falls_back_to_the_legacy_total_until_a_day_is_logged():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Work", "P1", hours=6.0)
    assert worklog.total_task_hours(task) == 6.0

    worklog.log_task_hours(task["id"], date.today().isoformat(), 2.5)
    task = worklog.list_tasks()[0]
    assert worklog.total_task_hours(task) == 2.5  # daily log now authoritative, legacy 6.0 no longer counted

    worklog.log_task_hours(task["id"], date.today().isoformat(), 0)  # cleared back out
    task = worklog.list_tasks()[0]
    assert worklog.total_task_hours(task) == 6.0  # falls back to legacy total again


def test_log_task_hours_increment_adds_on_top_of_existing_entry():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Focus-timed work", "P1")
    today = date.today().isoformat()

    worklog.log_task_hours_increment(task["id"], today, 0.5)
    assert worklog.list_tasks()[0]["daily_hours"] == {today: 0.5}

    worklog.log_task_hours_increment(task["id"], today, 0.25)
    assert worklog.list_tasks()[0]["daily_hours"] == {today: 0.75}


def test_log_task_hours_increment_rejects_non_positive_hours():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Work", "P1")
    with pytest.raises(ValueError):
        worklog.log_task_hours_increment(task["id"], date.today().isoformat(), 0)
    with pytest.raises(ValueError):
        worklog.log_task_hours_increment(task["id"], date.today().isoformat(), -0.5)


def test_log_task_hours_increment_requires_an_existing_task():
    with pytest.raises(ValueError):
        worklog.log_task_hours_increment("missing-id", date.today().isoformat(), 0.5)


def test_daily_summary_uses_daily_hours_when_present_instead_of_the_completion_lump_sum():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Spread across days", "P1", hours=99.0)  # legacy total ignored once logged by day
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    worklog.log_task_hours(task["id"], yesterday, 3.0)
    worklog.log_task_hours(task["id"], today, 2.0)

    # never marked Done - the old lump-sum rule would show nothing - but the daily log makes it show up anyway
    assert worklog.list_tasks()[0]["status"] == "New"
    assert worklog.daily_summary(yesterday)["by_project"] == {"P1": 3.0}
    assert worklog.daily_summary(today)["by_project"] == {"P1": 2.0}

    # correcting a day's entry (e.g. finished early) updates that day's report retroactively
    worklog.log_task_hours(task["id"], yesterday, 1.0)
    assert worklog.daily_summary(yesterday)["by_project"] == {"P1": 1.0}


def test_daily_summary_only_counts_tasks_marked_done_that_day(monkeypatch):
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Finish feature", "P1", hours=3.0)

    # not yet done - shouldn't show up in any daily summary
    today = date.today().isoformat()
    assert worklog.daily_summary(today)["tasks"] == []

    for _ in range(4):  # New -> Working -> Hold -> Review -> Done
        worklog.move_task_status(task["id"], 1)
    assert worklog.list_tasks()[0]["status"] == "Done"

    summary = worklog.daily_summary(today)
    assert len(summary["tasks"]) == 1
    assert summary["by_project"] == {"P1": 3.0}
    assert summary["total_hours"] == 3.0


def test_weekly_summary_aggregates_across_the_week():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Weekly work", "P1", hours=8.0)
    for _ in range(4):
        worklog.move_task_status(task["id"], 1)

    week_start = worklog.week_start_for(date.today().isoformat())
    weekly = worklog.weekly_summary(week_start)
    assert weekly["by_project"] == {"P1": 8.0}
    assert weekly["total_hours"] == 8.0
    assert len(weekly["days"]) == 7


def test_week_start_for_returns_the_preceding_monday():
    a_wednesday = "2026-08-26"
    assert date.fromisoformat(a_wednesday).weekday() == 2
    assert worklog.week_start_for(a_wednesday) == "2026-08-24"


def test_tasks_for_day_rolls_forward_not_done_tasks_to_every_day():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Still open", "P1")
    worklog.move_task_status(task["id"], 1)  # New -> Working, not Done

    yesterday = date.today() - timedelta(days=1)
    tomorrow = date.today() + timedelta(days=1)
    for day in (yesterday, date.today(), tomorrow):
        ids = [t["id"] for t in worklog.tasks_for_day(day)]
        assert task["id"] in ids


def test_tasks_for_day_only_shows_a_done_task_on_the_day_it_was_completed():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Wrap it up", "P1")
    for _ in range(4):  # New -> Working -> Hold -> Review -> Done
        worklog.move_task_status(task["id"], 1)

    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    assert task["id"] in [t["id"] for t in worklog.tasks_for_day(today)]
    assert task["id"] not in [t["id"] for t in worklog.tasks_for_day(yesterday)]
    assert task["id"] not in [t["id"] for t in worklog.tasks_for_day(tomorrow)]


def test_move_task_status_can_backdate_the_transition():
    worklog.add_project("Proj", "P1")
    task = worklog.add_task("Forgot to close this out", "P1", hours=3.0)
    yesterday = date.today() - timedelta(days=1)
    backdated_at = datetime(yesterday.year, yesterday.month, yesterday.day, 12, 0)

    for _ in range(4):
        worklog.move_task_status(task["id"], 1, at=backdated_at)
    updated = worklog.list_tasks()[0]
    assert updated["status"] == "Done"
    assert updated["status_history"][-1]["at"] == backdated_at.isoformat()

    # shows up on yesterday's board, not today's, and still counts in reports
    assert task["id"] in [t["id"] for t in worklog.tasks_for_day(yesterday)]
    assert task["id"] not in [t["id"] for t in worklog.tasks_for_day(date.today())]
    assert worklog.daily_summary(yesterday.isoformat())["total_hours"] == 3.0
