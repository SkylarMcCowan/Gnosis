from tools.base import Permission
from tools.knowledge.forget import KnowledgeForgetTool
from tools.knowledge.related import KnowledgeRelatedTool


def test_related_tool_forwards_topic_and_limit():
    calls = []
    tool = KnowledgeRelatedTool(lambda topic, limit=5: calls.append((topic, limit)) or [])

    assert tool.execute("books", limit=3) == []
    assert calls == [("books", 3)]
    assert tool.permission == Permission.SAFE


def test_forget_tool_requires_explicit_confirmation():
    calls = []
    tool = KnowledgeForgetTool(lambda path, confirm=False: calls.append((path, confirm)) or {"removed": confirm})

    assert tool.execute("notes.txt") == {"removed": False}
    assert calls == [("notes.txt", False)]
    assert tool.permission == Permission.REQUIRES_APPROVAL
