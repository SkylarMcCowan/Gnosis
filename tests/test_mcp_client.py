"""Tests for core/mcp_client.py's synchronous bridge to the async `mcp` SDK -
streamable_http_client/ClientSession are replaced with tiny fake async
context managers, no real network or event loop from a real MCP server
involved.
"""
import pytest

from core import mcp_client


class _FakeTool:
    def __init__(self, name, description, input_schema):
        self.name = name
        self.description = description
        self.input_schema = input_schema


class _FakeListToolsResult:
    def __init__(self, tools):
        self.tools = tools


class _FakeContentItem:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeCallToolResult:
    def __init__(self, text, is_error=False):
        self.content = [_FakeContentItem(text)] if text is not None else []
        self.is_error = is_error


class _FakeSession:
    last_instance = None

    def __init__(self, read_stream, write_stream):
        self.read_stream = read_stream
        self.write_stream = write_stream
        _FakeSession.last_instance = self

    async def initialize(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def list_tools(self):
        return _FakeListToolsResult([_FakeTool("echo", "Echo back text", {"type": "object"})])

    async def call_tool(self, name, arguments):
        if name == "boom":
            return _FakeCallToolResult("it broke", is_error=True)
        return _FakeCallToolResult(f"called {name} with {arguments}")


class _FakeTransport:
    def __init__(self, url):
        self.url = url

    async def __aenter__(self):
        return ("read-stream", "write-stream")

    async def __aexit__(self, *exc_info):
        return False


class _FailingTransport:
    def __init__(self, url):
        self.url = url

    async def __aenter__(self):
        raise ConnectionRefusedError("nobody home")

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def client(monkeypatch):
    c = mcp_client.MCPClient()
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession)
    yield c
    c.disconnect()


def test_call_tool_before_connect_raises(client):
    with pytest.raises(mcp_client.MCPError, match="Not connected"):
        client.call_tool("echo", {})


def test_connect_list_tools_and_call_tool_round_trip(monkeypatch, client):
    monkeypatch.setattr(mcp_client, "streamable_http_client", _FakeTransport)
    client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
    assert client.is_connected()

    tools = client.list_tools(timeout=5)
    assert tools == [{"name": "echo", "description": "Echo back text", "input_schema": {"type": "object"}}]

    result = client.call_tool("echo", {"text": "hi"}, timeout=5)
    assert result == "called echo with {'text': 'hi'}"


def test_call_tool_error_result_raises_mcp_error(monkeypatch, client):
    monkeypatch.setattr(mcp_client, "streamable_http_client", _FakeTransport)
    client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
    with pytest.raises(mcp_client.MCPError, match="it broke"):
        client.call_tool("boom", {}, timeout=5)


def test_connect_failure_raises_and_leaves_disconnected(monkeypatch, client):
    monkeypatch.setattr(mcp_client, "streamable_http_client", _FailingTransport)
    with pytest.raises(mcp_client.MCPError, match="nobody home"):
        client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
    assert not client.is_connected()


def test_disconnect_then_reconnect(monkeypatch, client):
    monkeypatch.setattr(mcp_client, "streamable_http_client", _FakeTransport)
    client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
    client.disconnect()
    assert not client.is_connected()

    client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
    assert client.is_connected()
    assert client.call_tool("echo", {}, timeout=5) == "called echo with {}"


def test_module_level_functions_delegate_to_the_default_client(monkeypatch):
    monkeypatch.setattr(mcp_client, "ClientSession", _FakeSession)
    monkeypatch.setattr(mcp_client, "streamable_http_client", _FakeTransport)
    try:
        assert mcp_client.is_connected() is False
        mcp_client.connect("http://localhost:9001/mcp/stream?userToken=abc", timeout=5)
        assert mcp_client.is_connected() is True
        assert mcp_client.list_tools(timeout=5)[0]["name"] == "echo"
    finally:
        mcp_client.disconnect()
