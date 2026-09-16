"""Penpot Studio pane: a chat scoped entirely to building things in the
user's self-hosted Penpot instance, through Penpot's own official MCP
server (help.penpot.app/mcp/) rather than the hand-rolled tools/design/
Tool wrappers - "Your account > Integrations > MCP Server" in Penpot gives
a ready-to-use URL like `<PENPOT_URL>/mcp/stream?userToken=<token>`; paste
that whole URL here and hit Connect.

Deliberately its own pane, not folded into the main chat's tool-selection
pool (tools/design/, webagent.py's _available_tool_actions()) - the whole
point is a place where every message is about Penpot and the model is
free to actually call MCP tools (including ones that mutate the file),
not a general assistant that only occasionally decides to.

The agent loop (run_agent_turn) uses the same model-agnostic JSON-decision
protocol as webagent.py's _select_tool_action - not Ollama's native
tools=, which this app's default local models don't reliably support -
except the tool catalog here is discovered live from list_tools() instead
of a fixed registry, since it depends on whatever the user's own Penpot
MCP server exposes (execute_code, high_level_overview, export_shape, ...
per help.penpot.app/mcp/, but not hardcoded here in case that set grows).
"""
import json
import os
import re

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from core import config as core_config
from core import mcp_client
from core.models import MODELS, chat as model_chat

_DEFAULT_MODEL = MODELS.get("coding", "qwen2.5-coder:7b")
_MAX_TOOL_CALLS_PER_TURN = 6


class PenpotStudioError(Exception):
    """Raised when a turn can't run - not connected to an MCP server yet."""


# ----------------------------------------------------------------------
# Config - just the one MCP URL (Penpot's own "Integrations > MCP Server"
# page already embeds the auth token in it as a query param)
# ----------------------------------------------------------------------
def _config_path():
    return os.path.join(core_config.path("penpot_studio"), "config.json")


def load_config():
    path = _config_path()
    if not os.path.isfile(path):
        return {"mcp_url": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"mcp_url": ""}
    return {"mcp_url": data.get("mcp_url", "") if isinstance(data, dict) else ""}


def save_config(mcp_url):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mcp_url": mcp_url}, f, indent=2)


# ----------------------------------------------------------------------
# Agent loop
# ----------------------------------------------------------------------
def _extract_json(content):
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(match.group(0) if match else content)
    except (ValueError, TypeError, AttributeError):
        return None


def _build_system_prompt(tools):
    lines = []
    for tool in tools:
        properties = ((tool.get("input_schema") or {}).get("properties")) or {}
        arg_names = ", ".join(properties.keys()) or "no arguments"
        lines.append(f"- {tool['name']}: {tool['description']} (arguments: {arg_names})")
    catalog_text = "\n".join(lines) if lines else "(no tools available)"
    return (
        "You are a design agent with direct, live access to the user's Penpot instance "
        "through the MCP tools below - use them to actually make the changes the user asks "
        "for, not just describe what they should look like.\n\n"
        f"Available tools:\n{catalog_text}\n\n"
        "Respond with ONLY valid JSON, nothing else: "
        '{"tool": "<tool name>", "arguments": {...}} to call one tool, or '
        '{"tool": null, "final_answer": "..."} once you are done (or no tool is needed) - '
        "final_answer is shown directly to the user, so make it a complete, plain-language reply.\n\n"
        "Call at most one tool per response. You will see its result and can call another, or finish."
    )


def run_agent_turn(conversation, model=None, max_tool_calls=_MAX_TOOL_CALLS_PER_TURN):
    """conversation: list of {"role", "content"} dicts ending with the
    user's newest message already appended. Returns (reply_text, tool_log,
    updated_conversation) - updated_conversation is `conversation` with
    every assistant/tool message this turn produced appended in place, so
    the caller can just store it back as the running history."""
    if not mcp_client.is_connected():
        raise PenpotStudioError("Not connected to Penpot's MCP server - paste an MCP URL and hit Connect first.")

    tools = mcp_client.list_tools()
    system_prompt = _build_system_prompt(tools)
    working = [{"role": "system", "content": system_prompt}] + conversation
    tool_log = []

    for _ in range(max_tool_calls):
        response = model_chat(model=model or _DEFAULT_MODEL, messages=working)
        content = response.get("message", {}).get("content", "")
        decision = _extract_json(content)

        if not isinstance(decision, dict) or not decision.get("tool"):
            reply = decision.get("final_answer") if isinstance(decision, dict) else None
            reply = reply or content or "(no reply)"
            conversation.append({"role": "assistant", "content": reply})
            return reply, tool_log, conversation

        name = decision.get("tool")
        arguments = decision.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}

        working.append({"role": "assistant", "content": content})
        conversation.append({"role": "assistant", "content": content})

        try:
            result = mcp_client.call_tool(name, arguments)
            error = None
        except mcp_client.MCPError as exc:
            result = None
            error = str(exc)
        tool_log.append({"tool": name, "arguments": arguments, "result": result, "error": error})

        tool_message = f"[Result of {name}]\n{result}" if error is None else f"[{name} failed]\n{error}"
        working.append({"role": "system", "content": tool_message})
        conversation.append({"role": "system", "content": tool_message})

    reply = "Hit the tool-call limit for this turn without a final answer - try again, maybe as a smaller step."
    conversation.append({"role": "assistant", "content": reply})
    return reply, tool_log, conversation


# ----------------------------------------------------------------------
# Qt layer
# ----------------------------------------------------------------------
class _ConnectWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            mcp_client.connect(self.url)
            tools = mcp_client.list_tools()
            self.done.emit(True, f"Connected - {len(tools)} tool(s) available.")
        except mcp_client.MCPError as exc:
            self.done.emit(False, str(exc))


class _TurnWorker(QThread):
    done = pyqtSignal(str, list, list)
    failed = pyqtSignal(str)

    def __init__(self, conversation, model=None):
        super().__init__()
        self.conversation = conversation
        self.model = model

    def run(self):
        try:
            reply, tool_log, updated = run_agent_turn(self.conversation, model=self.model)
            self.done.emit(reply, tool_log, updated)
        except Exception as exc:
            self.failed.emit(str(exc))


class PenpotStudioWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._conversation = []
        self._connected = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(10)

        title = QLabel("🎨 Penpot Studio")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        outer.addWidget(title)

        conn_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Penpot MCP URL - Your account > Integrations > MCP Server (includes your token)"
        )
        self.url_input.setText(load_config().get("mcp_url", ""))
        conn_row.addWidget(self.url_input, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._on_connect_clicked)
        conn_row.addWidget(self.connect_button)
        outer.addLayout(conn_row)

        self.status_label = QLabel("Not connected.")
        outer.addWidget(self.status_label)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        outer.addWidget(self.transcript, 1)

        input_row = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Describe what to build or change in Penpot...")
        self.message_input.returnPressed.connect(self._on_send_clicked)
        input_row.addWidget(self.message_input, 1)
        self.send_button = QPushButton("Send")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self.send_button)
        outer.addLayout(input_row)

    def _on_connect_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            self.status_label.setText("Paste your Penpot MCP URL first.")
            return
        save_config(url)
        self.status_label.setText("Connecting...")
        self.connect_button.setEnabled(False)
        worker = _ConnectWorker(url)
        worker.done.connect(self._on_connect_done)
        self._connect_worker = worker
        worker.start()

    def _on_connect_done(self, success, message):
        self.connect_button.setEnabled(True)
        self.status_label.setText(message)
        self._connected = success
        self.send_button.setEnabled(success)

    def _on_send_clicked(self):
        text = self.message_input.text().strip()
        if not text or not self._connected:
            return
        self._append_transcript("You", text)
        self.message_input.clear()
        self._conversation.append({"role": "user", "content": text})
        self.send_button.setEnabled(False)
        self.status_label.setText("Working...")
        worker = _TurnWorker(list(self._conversation))
        worker.done.connect(self._on_turn_done)
        worker.failed.connect(self._on_turn_failed)
        self._turn_worker = worker
        worker.start()

    def _on_turn_done(self, reply, tool_log, updated_conversation):
        self._conversation = updated_conversation
        for entry in tool_log:
            detail = entry.get("error") or entry.get("result") or ""
            self._append_transcript("🔧", f"{entry['tool']}({entry['arguments']}) -> {detail}")
        self._append_transcript("Agent", reply)
        self.status_label.setText("Connected.")
        self.send_button.setEnabled(True)

    def _on_turn_failed(self, message):
        self._append_transcript("Error", message)
        self.status_label.setText("Connected." if self._connected else "Not connected.")
        self.send_button.setEnabled(True)

    def _append_transcript(self, speaker, text):
        self.transcript.append(f"<b>{speaker}:</b> {text}")
