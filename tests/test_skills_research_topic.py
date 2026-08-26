"""Regression tests for skills/research/topic.py's ResearchTopicSkill in
isolation - tool_registry.execute is monkeypatched to a fake dispatcher so
these never touch a real tool. Wiring against the real tools is in
tests/test_skills_wiring.py.
"""
import skills.research.topic as research_topic
from skills.research.topic import ResearchTopicSkill, _filename_for_topic


class _FakeRegistry:
    def __init__(self, responses, calls):
        self._responses = responses
        self._calls = calls

    def execute(self, name, **kwargs):
        self._calls.append((name, kwargs))
        return self._responses.get(name)


def _fake_dispatcher(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(research_topic, "tool_registry", _FakeRegistry(responses, calls))
    return calls


def test_returns_existing_knowledge_without_searching_the_web(monkeypatch):
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [("stoicism.txt", "existing notes")],
    })

    result = ResearchTopicSkill().execute(topic="stoicism")

    assert result == {
        "topic": "stoicism", "source": "knowledge_base",
        "results": [("stoicism.txt", "existing notes")], "saved": False,
    }
    assert calls == [("knowledge.search", {"topic": "stoicism"})]


def test_searches_the_web_and_saves_findings_on_a_knowledge_miss(monkeypatch):
    search_results = [{"title": "T", "url": "https://example.com/a", "content": "snippet"}]
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [],
        "web.search": search_results,
        "web.fetch": "full page content",
        "knowledge.write": True,
    })

    result = ResearchTopicSkill().execute(topic="stoicism")

    assert result["source"] == "web"
    assert result["saved"] is True
    assert result["results"] == search_results
    assert calls == [
        ("knowledge.search", {"topic": "stoicism"}),
        ("web.search", {"query": "stoicism"}),
        ("web.fetch", {"url": "https://example.com/a"}),
        ("knowledge.write", {"filename": "research_stoicism.txt", "content": "full page content"}),
    ]


def test_reports_saved_false_when_knowledge_write_actually_fails(monkeypatch):
    """Real, reported bug: record_to_knowledge_base used to swallow a write
    failure silently and this skill hardcoded "saved": True regardless -
    the skill now trusts knowledge.write's real return value instead."""
    search_results = [{"title": "T", "url": "https://example.com/a", "content": "snippet"}]
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [],
        "web.search": search_results,
        "web.fetch": "full page content",
        "knowledge.write": False,
    })

    result = ResearchTopicSkill().execute(topic="stoicism")

    assert result["saved"] is False


def test_falls_back_to_the_search_snippet_when_fetch_returns_nothing(monkeypatch):
    search_results = [{"title": "T", "url": "https://example.com/a", "content": "snippet only"}]
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [],
        "web.search": search_results,
        "web.fetch": "",
        "knowledge.write": True,
    })

    ResearchTopicSkill().execute(topic="stoicism")

    assert calls[-1] == ("knowledge.write", {"filename": "research_stoicism.txt", "content": "snippet only"})


def test_does_not_fetch_when_the_top_result_has_no_url(monkeypatch):
    search_results = [{"title": "T", "content": "snippet only"}]
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [],
        "web.search": search_results,
        "knowledge.write": True,
    })

    ResearchTopicSkill().execute(topic="stoicism")

    called_tools = [name for name, _ in calls]
    assert "web.fetch" not in called_tools


def test_returns_no_results_and_does_not_save_when_the_web_search_is_empty(monkeypatch):
    calls = _fake_dispatcher(monkeypatch, {
        "knowledge.search": [],
        "web.search": [],
    })

    result = ResearchTopicSkill().execute(topic="stoicism")

    assert result == {"topic": "stoicism", "source": "web", "results": [], "saved": False}
    assert ("knowledge.write", {}) not in [(n, {}) for n, k in calls if n == "knowledge.write"]
    assert all(name != "knowledge.write" for name, _ in calls)


def test_filename_for_topic_sanitizes_and_prefixes():
    assert _filename_for_topic("stoicism") == "research_stoicism.txt"
    assert _filename_for_topic("what is love?") == "research_what_is_love.txt"
