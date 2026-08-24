"""Regression tests for /historian (webagent.py:3299-3596): dedupe/sort
knowledge_base, merge saved conversations into it, and dedupe agent_memory.

_historian_classify_topics is mocked in every test so no Ollama call happens -
its own model-classification behavior is a separate concern from historian's
file-management orchestration, which is what these tests guard.
"""
import json

import webagent


def _write_agent_memory(base_dir, agent, conversations):
    path = base_dir / "agent_memory"
    path.mkdir(exist_ok=True)
    (path / f"{agent}_memory.json").write_text(json.dumps({"conversations": conversations}))


def test_historian_dry_run_changes_nothing_on_disk(isolated_data_dir, monkeypatch):
    kb = isolated_data_dir / "knowledge_base"
    kb.mkdir()
    (kb / "note_a.txt").write_text("duplicate content")
    (kb / "note_b.txt").write_text("duplicate content")
    monkeypatch.setattr(webagent, "_historian_classify_topics", lambda titles, label="items": [None] * len(titles))

    stats = webagent.historian(dry_run=True)

    assert stats["knowledge_base"]["duplicates_removed"] == 1
    assert (kb / "note_a.txt").exists()
    assert (kb / "note_b.txt").exists()


def test_historian_real_run_dedupes_and_sorts_knowledge_base(isolated_data_dir, monkeypatch):
    kb = isolated_data_dir / "knowledge_base"
    kb.mkdir()
    (kb / "note_a.txt").write_text("duplicate content")
    (kb / "note_b.txt").write_text("duplicate content")
    (kb / "space_notes.txt").write_text("Notes about the overview effect and astronauts.")
    monkeypatch.setattr(
        webagent, "_historian_classify_topics",
        lambda titles, label="items": ["space"] * len(titles),
    )

    stats = webagent.historian(dry_run=False)

    assert stats["knowledge_base"]["duplicates_removed"] == 1
    # Every top-level file (the surviving duplicate plus space_notes.txt) gets
    # swept into its topic bucket - historian only ever leaves subfolders alone.
    remaining_flat = [p.name for p in kb.iterdir() if p.is_file()]
    assert remaining_flat == []
    assert (kb / "space").is_dir()
    assert len(list((kb / "space").iterdir())) == 2


def test_historian_merges_saved_conversations_into_knowledge_base(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent, "_historian_classify_topics", lambda titles, label="items": [None] * len(titles))
    convo_dir = isolated_data_dir / "conversations"
    convo_dir.mkdir()
    (convo_dir / "conv_20260101_000000.json").write_text(json.dumps({
        "conversation": [
            {"role": "user", "content": "What is the overview effect?"},
            {"role": "assistant", "content": "It's a shift in perspective astronauts report."},
        ]
    }))

    stats = webagent.historian(dry_run=False)

    assert stats["conversations"]["conversations_merged"] == 1
    assert stats["conversations"]["exchanges_saved"] == 1
    assert not (convo_dir / "conv_20260101_000000.json").exists()
    kb = isolated_data_dir / "knowledge_base"
    merged_files = list(kb.rglob("conversation_*.md"))
    assert len(merged_files) == 1
    assert "overview effect" in merged_files[0].read_text()


def test_historian_discards_saved_conversations_with_no_exchanges(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent, "_historian_classify_topics", lambda titles, label="items": [None] * len(titles))
    convo_dir = isolated_data_dir / "conversations"
    convo_dir.mkdir()
    (convo_dir / "empty.json").write_text(json.dumps({"conversation": [{"role": "system", "content": "seed"}]}))

    stats = webagent.historian(dry_run=False)

    assert stats["conversations"]["skipped_empty"] == 1
    assert not (convo_dir / "empty.json").exists()


def test_historian_cleans_agent_memory_duplicates(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(webagent, "_historian_classify_topics", lambda titles, label="items": [None] * len(titles))
    _write_agent_memory(isolated_data_dir, "ethics", [
        {"date": "2026-01-01T00:00:00", "summary": "discussed trolley problems", "topics": ["trolley"]},
        {"date": "2026-01-02T00:00:00", "summary": "discussed trolley problems", "topics": ["trolley"]},
    ])

    stats = webagent.historian(dry_run=False)

    assert stats["agent_memory"]["duplicates_removed"] == 1
    memory = webagent.load_agent_memory("ethics")
    assert len(memory) == 1
