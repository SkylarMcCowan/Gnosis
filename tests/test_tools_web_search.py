"""Regression tests for tools/web/search.py, the Phase 2 pilot tool."""
from tools.base import Permission
from tools.web.search import WebSearchTool


def test_execute_forwards_query_to_the_injected_search_function():
    calls = []

    def fake_search_web(query):
        calls.append(query)
        return [{"title": "Example", "url": "https://example.com"}]

    tool = WebSearchTool(fake_search_web)
    result = tool.execute(query="overview effect")

    assert calls == ["overview effect"]
    assert result == [{"title": "Example", "url": "https://example.com"}]


def test_tool_metadata():
    tool = WebSearchTool(lambda query: [])
    assert tool.name == "web.search"
    assert tool.permission == Permission.SAFE
