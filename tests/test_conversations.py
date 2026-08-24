"""Regression tests for /new, /conversations, and /loadconv (webagent.py:311-380)."""
import os

import webagent


def test_new_conversation_saves_current_when_it_has_content(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent.context, "assistant_convo", [
        webagent.sys_msgs.assistant_msg,
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ])

    saved_path = webagent.new_conversation()

    assert saved_path is not None
    assert webagent.context.assistant_convo == [webagent.sys_msgs.assistant_msg]
    assert webagent.list_conversations() == [os.path.basename(saved_path)]


def test_new_conversation_skips_save_when_only_seed_message_present(isolated_data_dir):
    saved_path = webagent.new_conversation()

    assert saved_path is None
    assert webagent.list_conversations() == []


def test_load_conversation_by_index(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent.context, "assistant_convo", [
        webagent.sys_msgs.assistant_msg,
        {"role": "user", "content": "remember this"},
        {"role": "assistant", "content": "I will"},
    ])
    webagent.new_conversation()
    assert len(webagent.list_conversations()) == 1

    loaded_path = webagent.load_conversation("1")

    assert loaded_path is not None
    assert {"role": "user", "content": "remember this"} in webagent.context.assistant_convo


def test_load_conversation_unknown_name_returns_none(isolated_data_dir):
    assert webagent.load_conversation("does_not_exist.json") is None
