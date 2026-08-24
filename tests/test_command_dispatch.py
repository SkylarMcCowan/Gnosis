"""Regression tests for the fourth Phase 1 extraction: webagent.py's ~50
inline if/elif command branches, now registered against a
core.command_router.CommandRouter instance (webagent._COMMAND_ROUTER).

Two things this suite is specifically for, beyond what each command's own
feature test file already covers by calling the underlying function
directly: (1) proving the *dispatch wiring* itself is correct - that a raw
prompt string actually reaches the right handler - and (2) covering the
mode-toggle commands Phase 0 explicitly skipped because they used to be
inline booleans with no independent function to call.
"""
import json

import pytest

import webagent


def dispatch(prompt):
    return webagent._COMMAND_ROUTER.dispatch(prompt)


def test_unknown_command_is_not_dispatched():
    assert dispatch("/not_a_real_command") is False


def test_reason_toggle():
    assert webagent.context.reasoning_mode is False
    dispatch("/reason")
    assert webagent.context.reasoning_mode is True
    dispatch("/REASON")  # case-insensitive, matches original `.lower()` check
    assert webagent.context.reasoning_mode is False


def test_deepthink_toggle_also_turns_on_web_search():
    webagent.context.web_search_mode = False
    dispatch("/deepthink")
    assert webagent.context.deep_think_mode is True
    assert webagent.context.web_search_mode is True


def test_unfiltered_and_coding_are_mutually_exclusive():
    dispatch("/unfiltered")
    assert webagent.context.unfiltered_mode is True
    dispatch("/coding")
    assert webagent.context.coding_mode is True
    assert webagent.context.unfiltered_mode is False


def test_tts_toggle(monkeypatch):
    monkeypatch.setattr(webagent, "has_tts_backend", lambda: True)
    dispatch("/tts")
    assert webagent.context.tts_mode is True


def test_tts_toggle_refuses_when_no_backend(monkeypatch, capsys):
    monkeypatch.setattr(webagent, "has_tts_backend", lambda: False)
    dispatch("/tts")
    assert webagent.context.tts_mode is False
    assert "unavailable" in capsys.readouterr().out.lower()


def test_websearch_toggle(monkeypatch):
    monkeypatch.setattr(webagent, "check_search_services", lambda: {"searxng": True})
    webagent.context.web_search_mode = False
    dispatch("/websearch")
    assert webagent.context.web_search_mode is True


def test_voice_toggle(monkeypatch):
    monkeypatch.setattr(webagent, "play_audio_effect", lambda effect_name: None)
    dispatch("/voice")
    assert webagent.context.voice_mode is True


def test_stopvoice(monkeypatch):
    monkeypatch.setattr(webagent, "stop_voice", lambda: None)
    assert dispatch("/stopvoice") is True


def test_clear_resets_conversation():
    webagent.context.assistant_convo.append({"role": "user", "content": "hello"})
    dispatch("/clear")
    assert webagent.context.assistant_convo == [webagent.sys_msgs.assistant_msg]


def test_help_prints_command_list(capsys):
    dispatch("/help")
    out = capsys.readouterr().out
    assert "/job" in out and "/cron" in out


def test_exit_raises_systemexit():
    with pytest.raises(SystemExit):
        dispatch("/exit")


def test_loadconv_with_an_argument_actually_dispatches(isolated_data_dir):
    """The bug this extraction fixed: /loadconv <arg> used to be nested
    inside an outer exact-match gate that only ever matched the bare
    "/loadconv" with no argument, so any real "/loadconv <file>" fell
    through to the unrecognized-command catch-all and never ran."""
    convo_dir = isolated_data_dir / "conversations"
    convo_dir.mkdir()
    (convo_dir / "conv_test.json").write_text(json.dumps({
        "conversation": [
            webagent.sys_msgs.assistant_msg,
            {"role": "user", "content": "remember this"},
        ]
    }))

    handled = dispatch("/loadconv 1")

    assert handled is True
    assert {"role": "user", "content": "remember this"} in webagent.context.assistant_convo


def test_loadconv_with_no_argument_lists_conversations(isolated_data_dir, capsys):
    handled = dispatch("/loadconv")
    assert handled is True
    assert "No saved conversations" in capsys.readouterr().out


def test_cron_bare_shows_help(no_real_crontab, capsys):
    dispatch("/cron")
    assert "/cron list" in capsys.readouterr().out


def test_cron_list_is_distinct_from_cron_bare(isolated_data_dir, no_real_crontab):
    webagent.cron_add(["0", "9", "*", "*", "*"], "feature", "news", description="Morning news")
    handled = dispatch("/cron list")
    assert handled is True
