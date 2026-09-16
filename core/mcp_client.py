"""A synchronous bridge to an MCP (Model Context Protocol) server.

The rest of Gnosis is built entirely on synchronous calls and QThread
workers, never asyncio - the official `mcp` SDK's ClientSession is
asyncio-only, so every call site would otherwise have to become async.
Instead, connect() spins up one dedicated background thread running its
own event loop and a live ClientSession for as long as the connection
lasts; list_tools()/call_tool() submit a coroutine onto that loop via
asyncio.run_coroutine_threadsafe-style plumbing and block the *calling*
thread (typically a QThread worker, never the GUI thread itself) until it
finishes. One connection at a time - connect() while already connected
replaces it.

No silent fallback: every failure (not connected, a bad URL, a tool that
reports isError, a timeout) raises MCPError rather than returning None or
an empty result (see MEMORY: "No silent fallbacks").

First real caller: penpot_studio.py, connecting to Penpot's own official
MCP server (self-hosted at <PENPOT_URL>/mcp/stream?userToken=<token> - see
docs/penpot.md) - nothing in this module is Penpot-specific, so it can
back any other MCP-based pane later too.
"""
import asyncio
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_CALL_TIMEOUT = 60


class MCPError(Exception):
    """Raised on any MCP failure - not connected, a connection error, a
    tool call that failed or timed out."""


class MCPClient:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._session = None
        self._request_queue = None
        self._ready = threading.Event()
        self._connect_error = None
        self._lock = threading.Lock()

    def is_connected(self):
        return self._session is not None

    def connect(self, url, timeout=DEFAULT_CONNECT_TIMEOUT):
        with self._lock:
            if self.is_connected():
                self._disconnect_locked()
            self._ready.clear()
            self._connect_error = None
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, args=(url,), daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout):
                self._disconnect_locked()
                raise MCPError(f"Timed out connecting to MCP server at {url!r}.")
            if self._connect_error is not None:
                error = self._connect_error
                self._disconnect_locked()
                raise MCPError(f"Failed to connect to MCP server at {url!r}: {error}")

    def disconnect(self):
        with self._lock:
            self._disconnect_locked()

    def _disconnect_locked(self):
        if self._loop is not None and self._request_queue is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._request_queue.put_nowait, None)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._session = None
        self._request_queue = None

    def _run_loop(self, url):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session_main(url))
        finally:
            self._loop.close()

    async def _session_main(self, url):
        self._request_queue = asyncio.Queue()
        try:
            async with streamable_http_client(url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    while True:
                        item = await self._request_queue.get()
                        if item is None:
                            break
                        coro_fn, future = item
                        try:
                            result = await coro_fn(session)
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(exc)
                        else:
                            if not future.done():
                                future.set_result(result)
        except Exception as exc:
            self._connect_error = exc
        finally:
            self._session = None
            self._ready.set()

    def _submit(self, coro_fn, timeout):
        if not self.is_connected():
            raise MCPError("Not connected to an MCP server - call connect(url) first.")
        future = Future()

        def _enqueue():
            self._request_queue.put_nowait((coro_fn, future))

        self._loop.call_soon_threadsafe(_enqueue)
        try:
            return future.result(timeout)
        except FutureTimeoutError as exc:
            raise MCPError(f"MCP request timed out after {timeout}s.") from exc

    def list_tools(self, timeout=DEFAULT_CONNECT_TIMEOUT):
        async def _call(session):
            result = await session.list_tools()
            return [
                {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}
                for tool in result.tools
            ]
        return self._submit(_call, timeout)

    def call_tool(self, name, arguments=None, timeout=DEFAULT_CALL_TIMEOUT):
        async def _call(session):
            result = await session.call_tool(name, arguments or {})
            text_parts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
            output = "\n".join(text_parts) if text_parts else ""
            if result.is_error:
                raise MCPError(output or f"MCP tool '{name}' reported an error.")
            return output
        return self._submit(_call, timeout)


_default_client = MCPClient()


def connect(url, timeout=DEFAULT_CONNECT_TIMEOUT):
    _default_client.connect(url, timeout=timeout)


def is_connected():
    return _default_client.is_connected()


def list_tools(timeout=DEFAULT_CONNECT_TIMEOUT):
    return _default_client.list_tools(timeout=timeout)


def call_tool(name, arguments=None, timeout=DEFAULT_CALL_TIMEOUT):
    return _default_client.call_tool(name, arguments, timeout=timeout)


def disconnect():
    _default_client.disconnect()
