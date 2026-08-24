import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webagent  # noqa: E402  (must follow the sys.path fix above)
from core import config as core_config  # noqa: E402


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect every on-disk store webagent resolves through
    core.config.project_root() (agent_memory/, knowledge_base/, tutor_paths/,
    cron/, conversations/) into a scratch directory, so tests never read or
    write the project's real data."""
    monkeypatch.setattr(core_config, "_root_override", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def reset_global_state(monkeypatch):
    """Every test starts from the same clean, deterministic session state,
    regardless of what an earlier test toggled. All of this now lives on the
    shared webagent.context object (core/context.py) rather than as separate
    webagent.py globals."""
    monkeypatch.setattr(webagent.context, "assistant_convo", [webagent.sys_msgs.assistant_msg])
    monkeypatch.setattr(webagent.context, "current_agent", None)
    monkeypatch.setattr(webagent.context, "web_search_mode", False)
    monkeypatch.setattr(webagent.context, "deep_think_mode", False)
    monkeypatch.setattr(webagent.context, "unfiltered_mode", False)
    monkeypatch.setattr(webagent.context, "reasoning_mode", False)
    monkeypatch.setattr(webagent.context, "coding_mode", False)
    monkeypatch.setattr(webagent.context, "tts_mode", False)
    monkeypatch.setattr(webagent.context, "voice_mode", False)


class FakeOllamaChat:
    """Stand-in for ollama.chat(). Records every call and returns a canned reply.

    Handles both streaming (an iterable of {"message": {"content": ...}} chunks)
    and non-streaming calls, matching the two calling conventions used across
    webagent.py.
    """

    def __init__(self, reply="Hello from the fake model."):
        self.reply = reply
        self.calls = []

    def __call__(self, model, messages, stream=False, **kwargs):
        self.calls.append({"model": model, "messages": messages, "stream": stream, **kwargs})
        if stream:
            return iter([{"message": {"content": self.reply}}])
        return {"message": {"content": self.reply}}


@pytest.fixture
def fake_ollama_chat(monkeypatch):
    if webagent.ollama is None:
        pytest.skip("ollama package is not importable in this environment")
    fake = FakeOllamaChat()
    monkeypatch.setattr(webagent.ollama, "chat", fake)
    return fake


@pytest.fixture
def no_real_crontab(monkeypatch):
    """Redirect cron_add/cron_edit/cron_remove away from the real system crontab
    onto an in-memory fake, so the test suite never mutates the user's actual cron."""
    state = {"text": ""}

    def fake_read():
        return state["text"]

    def fake_write(text):
        state["text"] = text
        return True

    monkeypatch.setattr(webagent, "_read_crontab", fake_read)
    monkeypatch.setattr(webagent, "_write_crontab", fake_write)
    return state
