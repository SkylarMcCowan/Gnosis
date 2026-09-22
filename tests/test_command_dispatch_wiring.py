"""Wiring-correctness sweep for core/command_router.py's registration table.

test_command_dispatch.py already covers the mode toggles and the /loadconv
bug fix by exercising real behavior end to end. This file covers the rest
of the ~50 registered commands - the ones whose *underlying* function is
already well-tested elsewhere (Phase 0) but whose *dispatch wiring* (does
this exact prompt string reach that function, with arguments parsed the way
the handler is supposed to parse them) was never itself verified. Each test
mocks the one underlying function a handler calls and asserts it was
reached with the right arguments - it does not re-verify what that function
does, only that the router table actually gets prompts to it.
"""
import tarot
import webagent


def dispatch(prompt):
    return webagent._COMMAND_ROUTER.dispatch(prompt)


def test_password_dispatches_with_parsed_args(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "password_command", lambda args: calls.append(args))
    assert dispatch("/password -3") is True
    assert calls == ["-3"]


def test_password_bare_dispatches_with_no_args(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "password_command", lambda args: calls.append(args))
    dispatch("/password")
    assert calls == [None]


def test_job_dispatches_with_parsed_args(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(webagent, "job_command", lambda args: calls.append(args) or "result")
    dispatch("/job ethics")
    assert calls == ["ethics"]
    assert "result" in capsys.readouterr().out


def test_historian_dispatches_dry_run_correctly(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "historian", lambda dry_run: calls.append(dry_run))
    dispatch("/historian preview")
    dispatch("/historian")
    assert calls == [True, False]


def test_cron_alarm_dispatches_with_parsed_time_and_message(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "set_alarm", lambda desc, message: calls.append((desc, message)) or (None, "no crontab"))
    dispatch("/cron alarm in 5 minutes message: tea is ready")
    assert calls == [("in 5 minutes", "tea is ready")]


def test_cron_add_dispatches_with_parsed_fields(monkeypatch, isolated_data_dir, no_real_crontab):
    calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.add"), "_add_fn",
        lambda fields, action_type, payload, description=None, one_shot=False: calls.append((fields, action_type, payload)) or ("abc123", None),
    )
    dispatch("/cron add 0 9 * * * prompt: good morning")
    assert calls == [(["0", "9", "*", "*", "*"], "prompt", "good morning")]


def test_cron_edit_dispatches_with_parsed_index_and_fields(monkeypatch, isolated_data_dir, no_real_crontab):
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.list"), "_list_fn",
        lambda: ([{"kind": "gnosis", "task_id": "abc"}], None),
    )
    calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.edit"), "_edit_fn",
        lambda task_id, schedule_fields, action_type, action_payload, description=None, one_shot=None: calls.append(
            (task_id, schedule_fields, action_type, action_payload)
        ) or (True, None),
    )
    dispatch("/cron edit 1 30 10 * * * prompt: updated text")
    assert calls == [("abc", ["30", "10", "*", "*", "*"], "prompt", "updated text")]


def test_cron_remove_dispatches_with_parsed_index(monkeypatch, capsys, isolated_data_dir, no_real_crontab):
    monkeypatch.setattr(webagent, "print_cron_list", lambda: [{"kind": "gnosis", "task_id": "abc"}])
    monkeypatch.setattr(webagent, "_next_prompt_line", lambda label: "y")
    calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.remove"), "_remove_fn",
        lambda index: calls.append(index) or (True, {}),
    )
    dispatch("/cron remove 1")
    assert calls == [1]


def test_cron_run_dispatches_with_parsed_index(monkeypatch, isolated_data_dir, no_real_crontab):
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.list"), "_list_fn",
        lambda: ([{"kind": "gnosis", "task_id": "abc"}], None),
    )
    calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("cron.run"), "_run_fn",
        lambda task_id: calls.append(task_id) or (True, "ok"),
    )
    dispatch("/cron run 1")
    assert calls == ["abc"]


def test_askwiki_dispatches_with_parsed_query(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "ask_wiki", lambda query: calls.append(query))
    dispatch("/askwiki who was Ada Lovelace")
    assert calls == ["who was Ada Lovelace"]


def test_tutor_dispatches_with_parsed_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "tutor", lambda topic: calls.append(topic))
    dispatch("/tutor recursion")
    assert calls == ["recursion"]


def test_showpath_dispatches_with_parsed_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "show_learning_path", lambda topic: calls.append(topic))
    dispatch("/showpath stoicism")
    dispatch("/showpath")
    assert calls == ["stoicism", None]


def test_delpath_dispatches_with_parsed_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "delete_learning_path", lambda topic: calls.append(topic))
    dispatch("/delpath stoicism")
    assert calls == ["stoicism"]


def test_news_dispatches_with_parsed_args(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "news_command", lambda args: calls.append(args))
    dispatch("/news technology")
    dispatch("/news")
    assert calls == ["technology", None]


def test_ytdl_dispatches_with_parsed_url(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "ytdl_command", lambda url: calls.append(url))
    dispatch("/ytdl https://youtu.be/abc123")
    assert calls == ["https://youtu.be/abc123"]


def test_profile_bare_shows_current_profile(monkeypatch, capsys):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {
        "name": "Skylar", "location": "", "persona": "neutral",
        "preferences": [], "interests": [], "recent_explorations": [], "notes": "",
    })
    dispatch("/profile")
    assert "Skylar" in capsys.readouterr().out


def test_profile_persona_dispatches_with_parsed_value(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {"persona": "neutral"})
    calls = []
    monkeypatch.setattr(webagent, "set_user_persona", lambda value: calls.append(value) or (True, {"persona": value}))
    dispatch("/profile persona cheery")
    assert calls == ["cheery"]


def test_persona_shortcut_dispatches_with_parsed_value(monkeypatch):
    monkeypatch.setattr(webagent, "load_user_profile", lambda: {"persona": "neutral"})
    calls = []
    monkeypatch.setattr(webagent, "set_user_persona", lambda value: calls.append(value) or (True, {"persona": value}))
    dispatch("/persona cheery")
    assert calls == ["cheery"]


def test_selfimprove_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "perform_self_improve", lambda dry_run=False: calls.append(dry_run))
    dispatch("/selfimprove")
    assert calls == [False]


def test_selfimprove_preview_dispatches_as_a_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "perform_self_improve", lambda dry_run=False: calls.append(dry_run))
    dispatch("/selfimprove preview")
    dispatch("/selfimprove --dry-run")
    assert calls == [True, True]


def test_learning_dispatches_and_reports_with_no_history(isolated_data_dir, capsys):
    dispatch("/learning")
    assert "No self-improve attempts recorded yet." in capsys.readouterr().out


def test_learning_reports_a_real_recorded_experience(isolated_data_dir, capsys):
    from memory.experience import build_experience, record_experience
    record_experience(build_experience(goal="fix target.py", success=True, agent="self-improve"))

    dispatch("/learning")

    out = capsys.readouterr().out
    assert "1 succeeded" in out
    assert "100%" in out


def test_unsupervised_dispatches(monkeypatch, isolated_data_dir, capsys):
    monkeypatch.setattr(webagent, "run_overnight_cycle", lambda: "research report")
    dispatch("/unsupervised")
    assert "research report" in capsys.readouterr().out


def test_report_dispatches_and_prints_a_real_metrics_report(isolated_data_dir, capsys):
    dispatch("/report")
    out = capsys.readouterr().out
    assert "Observability report" in out
    assert "No searches recorded yet." in out
    assert "No recorded self-improve attempts yet." in out


def test_report_reflects_real_recorded_activity_and_experiences(isolated_data_dir, capsys):
    from core.activity_log import record_activity
    from memory.experience import build_experience, record_experience

    record_activity("SEARCH_COMPLETED", query="stoicism", result_count=3)
    record_activity("TASK_COMPLETED", agent_name="research", user_input="x", response="y")
    record_experience(build_experience(
        goal="Fix target.py: add() is wrong", success=True,
        tools_used=["repo.audit", "test.run"], agent="self-improve",
    ))

    dispatch("/report")
    out = capsys.readouterr().out

    assert "1 searches" in out
    assert "research: 1" in out
    assert "target.py: 1 attempt(s), 1 succeeded" in out
    assert "repo.audit: used 1x, 100% in a successful outcome" in out
    assert "1 attempted, 100% succeeded" in out


def test_new_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "new_conversation", lambda save_current: calls.append(save_current))
    dispatch("/new")
    assert calls == [True]


def test_conversations_dispatches(monkeypatch, capsys):
    monkeypatch.setattr(webagent, "list_conversations", lambda: ["a.json"])
    dispatch("/conversations")
    assert "a.json" in capsys.readouterr().out


def test_archives_dispatches_with_parsed_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(
        webagent.tool_registry.get("knowledge.search"), "_search_fn",
        lambda topic: calls.append(topic) or [],
    )
    dispatch("/archives stoicism")
    assert calls == ["stoicism"]


def test_tarot_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(tarot, "tarot_reading", lambda: calls.append(True))
    dispatch("/tarot")
    assert calls == [True]


def test_createpath_dispatches_with_parsed_topic_and_resources(monkeypatch):
    calls = []
    monkeypatch.setattr(webagent, "create_learning_path", lambda topic, resources: calls.append((topic, resources)))
    dispatch("/createpath stoicism Meditations,Letters from a Stoic")
    assert calls == [("stoicism", ["Meditations", "Letters from a Stoic"])]


def test_reindexevidence_dispatches(monkeypatch, capsys):
    monkeypatch.setattr(webagent, "backfill_web_evidence_metadata", lambda: 7)
    dispatch("/reindexevidence")
    assert "7" in capsys.readouterr().out
