"""Tests for penpot_studio.py's backend - config storage and the
run_agent_turn() control flow. mcp_client and core.models.chat are both
faked; no real MCP server or Ollama daemon involved."""
import pytest

import penpot_studio
from core import mcp_client


def test_load_config_defaults_to_empty_url(isolated_data_dir):
    assert penpot_studio.load_config() == {"mcp_url": ""}


def test_save_and_load_config_round_trips(isolated_data_dir):
    penpot_studio.save_config("http://localhost:9001/mcp/stream?userToken=abc")
    assert penpot_studio.load_config() == {"mcp_url": "http://localhost:9001/mcp/stream?userToken=abc"}


def test_run_agent_turn_raises_when_not_connected(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: False)
    with pytest.raises(penpot_studio.PenpotStudioError, match="Not connected"):
        penpot_studio.run_agent_turn([{"role": "user", "content": "hi"}])


def _fake_tools():
    return [{"name": "execute_code", "description": "Run JS against the open file", "input_schema": {"properties": {"code": {}}}}]


def test_run_agent_turn_returns_final_answer_with_no_tool_call(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: True)
    monkeypatch.setattr(mcp_client, "list_tools", _fake_tools)
    monkeypatch.setattr(
        penpot_studio, "model_chat",
        lambda model, messages: {"message": {"content": '{"tool": null, "final_answer": "All set."}'}},
    )

    conversation = [{"role": "user", "content": "what's in my file?"}]
    reply, tool_log, updated = penpot_studio.run_agent_turn(conversation)

    assert reply == "All set."
    assert tool_log == []
    assert updated[-1] == {"role": "assistant", "content": "All set."}


def test_run_agent_turn_calls_a_tool_then_finishes(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: True)
    monkeypatch.setattr(mcp_client, "list_tools", _fake_tools)
    monkeypatch.setattr(mcp_client, "call_tool", lambda name, arguments: "board created")

    responses = iter([
        '{"tool": "execute_code", "arguments": {"code": "add a board"}}',
        '{"tool": null, "final_answer": "Added the board."}',
    ])
    monkeypatch.setattr(
        penpot_studio, "model_chat",
        lambda model, messages: {"message": {"content": next(responses)}},
    )

    conversation = [{"role": "user", "content": "add a board"}]
    reply, tool_log, updated = penpot_studio.run_agent_turn(conversation)

    assert reply == "Added the board."
    assert tool_log == [{"tool": "execute_code", "arguments": {"code": "add a board"}, "result": "board created", "error": None}]
    assert any(m["role"] == "system" and "board created" in m["content"] for m in updated)


def test_run_agent_turn_surfaces_a_failed_tool_call_and_keeps_going(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: True)
    monkeypatch.setattr(mcp_client, "list_tools", _fake_tools)

    def fake_call_tool(name, arguments):
        raise mcp_client.MCPError("bad code")
    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)

    responses = iter([
        '{"tool": "execute_code", "arguments": {"code": "oops"}}',
        '{"tool": null, "final_answer": "Let me try something else."}',
    ])
    monkeypatch.setattr(
        penpot_studio, "model_chat",
        lambda model, messages: {"message": {"content": next(responses)}},
    )

    reply, tool_log, updated = penpot_studio.run_agent_turn([{"role": "user", "content": "add a board"}])

    assert reply == "Let me try something else."
    assert tool_log[0]["error"] == "bad code"
    assert tool_log[0]["result"] is None


def test_run_agent_turn_falls_back_to_raw_content_when_unparseable(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: True)
    monkeypatch.setattr(mcp_client, "list_tools", _fake_tools)
    monkeypatch.setattr(
        penpot_studio, "model_chat",
        lambda model, messages: {"message": {"content": "just a plain sentence, not JSON"}},
    )

    reply, tool_log, updated = penpot_studio.run_agent_turn([{"role": "user", "content": "hi"}])

    assert reply == "just a plain sentence, not JSON"
    assert tool_log == []


def test_run_agent_turn_stops_at_the_tool_call_limit(monkeypatch):
    monkeypatch.setattr(mcp_client, "is_connected", lambda: True)
    monkeypatch.setattr(mcp_client, "list_tools", _fake_tools)
    monkeypatch.setattr(mcp_client, "call_tool", lambda name, arguments: "ok")
    monkeypatch.setattr(
        penpot_studio, "model_chat",
        lambda model, messages: {"message": {"content": '{"tool": "execute_code", "arguments": {}}'}},
    )

    reply, tool_log, updated = penpot_studio.run_agent_turn([{"role": "user", "content": "loop forever"}], max_tool_calls=2)

    assert "tool-call limit" in reply
    assert len(tool_log) == 2
