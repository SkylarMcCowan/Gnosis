"""Regression tests for tools/knowledge/search.py and tools/knowledge/write.py."""
from tools.base import Permission
from tools.knowledge.search import KnowledgeSearchTool
from tools.knowledge.write import KnowledgeWriteTool


def test_knowledge_search_forwards_topic():
    calls = []

    def fake_search(topic):
        calls.append(topic)
        return [("note.md", "content about stoicism")]

    tool = KnowledgeSearchTool(fake_search)
    assert tool.execute(topic="stoicism") == [("note.md", "content about stoicism")]
    assert calls == ["stoicism"]


def test_knowledge_search_metadata():
    tool = KnowledgeSearchTool(lambda topic: [])
    assert tool.name == "knowledge.search"
    assert tool.permission == Permission.SAFE


def test_knowledge_write_forwards_filename_and_content():
    calls = []

    def fake_write(filename, content):
        calls.append((filename, content))

    tool = KnowledgeWriteTool(fake_write)
    tool.execute(filename="note.md", content="hello")
    assert calls == [("note.md", "hello")]


def test_knowledge_write_metadata():
    tool = KnowledgeWriteTool(lambda filename, content: None)
    assert tool.name == "knowledge.write"
    assert tool.permission == Permission.RESTRICTED
