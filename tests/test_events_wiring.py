"""Regression tests for Phase 12's event-bus wiring: real call sites
publish real events, and the subscribers registered once at webagent.py
import time (_register_event_subscribers) actually react - both the
generic activity logger and the TASK_COMPLETED-specific handler that
replaced the old duplicated direct-call chains.
"""
import webagent
from core.activity_log import load_activity
from core.events import events


def test_every_wired_event_has_the_activity_logger_subscribed():
    for event_name in ("SEARCH_COMPLETED", "TASK_COMPLETED", "SKILL_CREATED",
                       "KNOWLEDGE_UPDATED", "MEMORY_CREATED", "TEST_PASSED", "TEST_FAILED"):
        assert len(events._subscribers.get(event_name, [])) >= 1


def test_task_completed_has_the_domain_specific_handler_subscribed():
    handlers = events._subscribers.get("TASK_COMPLETED", [])
    assert webagent._on_task_completed in handlers


def test_search_web_publishes_search_completed(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent, "search_searx", lambda query: [{"title": "x", "url": "https://a.com", "content": "..."}])

    webagent.search_web("astronomy")

    entries = load_activity(event_name="SEARCH_COMPLETED")
    assert len(entries) == 1
    assert entries[0]["query"] == "astronomy"
    assert entries[0]["result_count"] == 1


def test_save_agent_memory_publishes_memory_created(isolated_data_dir):
    webagent.save_agent_memory("research", "a summary")

    entries = load_activity(event_name="MEMORY_CREATED")
    assert len(entries) == 1
    assert entries[0]["agent_name"] == "research"


def test_record_to_knowledge_base_publishes_knowledge_updated(isolated_data_dir):
    webagent.record_to_knowledge_base("notes.txt", "content")

    entries = load_activity(event_name="KNOWLEDGE_UPDATED")
    assert len(entries) == 1
    assert entries[0]["filename"] == "notes.txt"


def test_run_self_improve_tests_publishes_test_passed_on_success(isolated_data_dir, tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n")

    webagent._run_self_improve_tests(cwd=str(tmp_path))

    entries = load_activity(event_name="TEST_PASSED")
    assert len(entries) == 1


def test_run_self_improve_tests_publishes_test_failed_on_vacuous_pass(isolated_data_dir, tmp_path):
    (tmp_path / "tests").mkdir()

    webagent._run_self_improve_tests(cwd=str(tmp_path))

    entries = load_activity(event_name="TEST_FAILED")
    assert len(entries) == 1


def test_task_completed_triggers_the_real_memory_save(isolated_data_dir, fake_ollama_chat, monkeypatch):
    """Confirms the subscriber produces the same real effect the old
    direct call used to - not just that an event fired."""
    webagent.context.web_search_mode = False
    webagent.context.current_agent = "research"
    monkeypatch.setattr(webagent, "should_save_to_knowledge_base", lambda *a, **k: False)

    webagent.chat_response("tell me about stoicism")

    memory_file = isolated_data_dir / "agent_memory" / "research_memory.json"
    assert memory_file.exists()
    entries = load_activity(event_name="TASK_COMPLETED")
    assert len(entries) == 1
    assert entries[0]["agent_name"] == "research"
