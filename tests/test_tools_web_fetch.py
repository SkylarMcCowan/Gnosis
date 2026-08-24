"""Regression tests for tools/web/fetch.py."""
from tools.base import Permission
from tools.web.fetch import WebFetchTool


def test_execute_forwards_url_to_the_injected_fetch_function():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return "page content"

    tool = WebFetchTool(fake_fetch)
    assert tool.execute(url="https://example.com") == "page content"
    assert calls == ["https://example.com"]


def test_tool_metadata():
    tool = WebFetchTool(lambda url: None)
    assert tool.name == "web.fetch"
    assert tool.permission == Permission.SAFE
