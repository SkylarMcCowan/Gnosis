from tools.base import Permission
from tools.conversation.inspect import ConversationInspectTool


def test_conversation_inspect_tool_forwards_to_inspector():
    calls = []
    tool = ConversationInspectTool(lambda: calls.append(True) or {"active_topic": "books"})

    assert tool.permission == Permission.SAFE
    assert tool.execute() == {"active_topic": "books"}
    assert calls == [True]
