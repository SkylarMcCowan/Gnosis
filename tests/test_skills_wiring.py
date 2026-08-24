"""Confirms webagent.py actually registers its real Skill(s) with the
shared skills.registry.registry, composing the *real* registered tools -
not just that ResearchTopicSkill works in isolation
(tests/test_skills_research_topic.py already covers that). Same pattern as
tests/test_tools_wiring.py: mock each tool's own underlying dependency
(search_searx, requests.get), never the tool itself, and round-trip through
the real, isolated filesystem for the knowledge steps.
"""
from skills.registry import registry as skill_registry
import webagent


def test_research_topic_skill_is_registered_and_reaches_the_real_tools(isolated_data_dir, monkeypatch):
    skill = skill_registry.get("research.topic")
    assert skill is not None

    monkeypatch.setattr(
        webagent, "search_searx",
        lambda query: [{"title": "Example", "url": "https://example.com", "content": "web snippet"}],
    )

    class FakeResponse:
        status_code = 200
        text = (
            "<html><body><p>real fetched page content, deliberately long "
            "enough to clear the extractor's minimum content threshold so "
            "it doesn't fall back to a placeholder string instead.</p></body></html>"
        )

    monkeypatch.setattr(webagent.requests, "get", lambda *a, **k: FakeResponse())

    result = skill_registry.execute("research.topic", topic="astronomy")

    assert result["source"] == "web"
    assert result["saved"] is True
    saved_path = isolated_data_dir / "knowledge_base" / "research_astronomy.txt"
    assert saved_path.exists()
    assert "real fetched page content" in saved_path.read_text()


def test_research_topic_skill_reuses_existing_knowledge_without_a_web_search(isolated_data_dir, monkeypatch):
    kb_dir = isolated_data_dir / "knowledge_base"
    kb_dir.mkdir()
    (kb_dir / "astronomy_notes.txt").write_text("Astronomy is the study of celestial objects.")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not search the web when knowledge already exists")

    monkeypatch.setattr(webagent, "search_searx", fail_if_called)

    result = skill_registry.execute("research.topic", topic="astronomy")

    assert result["source"] == "knowledge_base"
    assert result["saved"] is False
    assert result["results"][0][0] == "astronomy_notes.txt"
