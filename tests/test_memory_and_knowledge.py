"""Regression tests for agent memory (webagent.py:2350-2422) and the
knowledge base (webagent.py:2565-2618). Uses isolated_data_dir so nothing
touches the real agent_memory/ or knowledge_base/ directories on disk.
"""
import webagent


def test_agent_memory_round_trip(isolated_data_dir):
    assert webagent.load_agent_memory("ethics") == []

    webagent.save_agent_memory("ethics", "User asked about trolley problems and consequentialism.")
    memory = webagent.load_agent_memory("ethics")

    assert len(memory) == 1
    assert "trolley problems" in memory[0]["summary"]
    assert "trolley" in memory[0]["topics"] or "problems" in memory[0]["topics"]


def test_agent_memory_is_isolated_per_agent(isolated_data_dir):
    webagent.save_agent_memory("ethics", "ethics conversation")
    webagent.save_agent_memory("research", "research conversation")

    assert len(webagent.load_agent_memory("ethics")) == 1
    assert len(webagent.load_agent_memory("research")) == 1
    assert webagent.load_agent_memory("comedian") == []


def test_agent_memory_caps_at_twenty_conversations(isolated_data_dir):
    for i in range(25):
        webagent.save_agent_memory("ethics", f"conversation number {i}")

    memory = webagent.load_agent_memory("ethics")
    assert len(memory) == 20
    assert "number 24" in memory[-1]["summary"]


def test_knowledge_base_round_trip(isolated_data_dir):
    webagent.record_to_knowledge_base("stoicism_notes.md", "Marcus Aurelius on impermanence.")

    results = webagent.search_knowledge_base("Marcus Aurelius")
    assert len(results) == 1
    filename, content = results[0]
    assert filename == "stoicism_notes.md"
    assert "impermanence" in content


def test_knowledge_base_search_is_case_insensitive_and_scoped(isolated_data_dir):
    webagent.record_to_knowledge_base("a.md", "Something about OVERVIEW EFFECT and astronauts.")
    webagent.record_to_knowledge_base("b.md", "Unrelated content about baking bread.")

    results = webagent.search_knowledge_base("overview effect")
    assert [name for name, _ in results] == ["a.md"]


def test_user_can_edit_pin_and_forget_memory(isolated_data_dir):
    webagent.save_agent_memory('default', 'I follow Manchester United.')
    date = webagent.load_agent_memory('default')[0]['date']
    webagent.update_agent_memory('default', date, summary='I follow Arsenal.', pinned=True)
    for i in range(25):
        webagent.save_agent_memory('default', f'New conversation number {i}')
    entries = webagent.load_agent_memory('default')
    assert len(entries) == 20
    assert any(entry.get('pinned') and entry['summary'] == 'I follow Arsenal.' for entry in entries)
    assert 'Arsenal' in webagent.get_relevant_agent_memory('default', 'greeting')
    webagent.update_agent_memory('default', date, forget=True)
    assert all(entry['date'] != date for entry in webagent.load_agent_memory('default'))


def test_saved_notes_cannot_independently_corroborate_web_results():
    notes = {'url': 'knowledge_base://notes.txt', 'search_provider': 'knowledge-base',
             'content': 'Census population 331 million', 'truthfulness_confidence': 40}
    live = {'url': 'https://example.org/census', 'content': notes['content']}
    webagent.apply_corroboration([notes, live])
    assert live['corroborating_domains'] == []
    assert notes['truthfulness_confidence'] == 40
