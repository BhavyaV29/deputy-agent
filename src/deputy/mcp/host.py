"""A synchronous host over asynchronous MCP servers.

The MCP SDK is async and its client sessions hold anyio cancel scopes that must
be entered and exited on the same task. The agent loop, by contrast, is blocking.
:class:`McpHost` reconciles the two by owning a private event loop on a daemon
thread: every session is opened and later closed by one long-lived caretaker
coroutine (satisfying anyio), while tool calls are dispatched onto that loop from
the calling thread and awaited synchronously. Callers only ever see blocking
methods.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from concurrent.futures import Future
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from types import TracebackType
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent, ToolAnnotations

Connector = Callable[[], AbstractAsyncContextManager[ClientSession]]

_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


class McpToolError(RuntimeError):
    """An MCP tool ran but reported failure, or the call could not be delivered."""


@dataclass(frozen=True)
class ServerSpec:
    """How to launch one stdio MCP server as a subprocess."""

    command: str
    args: Sequence[str] = ()
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveredTool:
    server: str
    name: str
    description: str
    input_schema: Mapping[str, Any]
    mutating: bool


def stdio_connector(spec: ServerSpec) -> Connector:
    params = StdioServerParameters(
        command=spec.command,
        args=list(spec.args),
        env={**os.environ, **spec.env},
    )

    @asynccontextmanager
    async def connect() -> AsyncIterator[ClientSession]:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    return connect


def memory_connector(server: FastMCP) -> Connector:
    """An in-process connector to a server object — no subprocess, for tests."""
    return lambda: create_connected_server_and_client_session(server)


class McpHost:
    def __init__(self, connectors: Mapping[str, Connector], *, call_timeout: float = 30.0) -> None:
        self._connectors = dict(connectors)
        self._call_timeout = call_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, ClientSession] = {}
        self._tools: list[DiscoveredTool] = []
        self._caretaker: Future[None] | None = None
        self._shutdown: asyncio.Event | None = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> None:
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="deputy-mcp", daemon=True)
        thread.start()
        self._loop, self._thread = loop, thread

        ready: Future[None] = Future()
        self._caretaker = asyncio.run_coroutine_threadsafe(self._caretake(ready), loop)
        try:
            ready.result()
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        if self._shutdown is not None and self._caretaker is not None:
            loop.call_soon_threadsafe(self._shutdown.set)
            self._caretaker.result(timeout=self._call_timeout)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=self._call_timeout)
        loop.close()
        self._loop = self._thread = self._caretaker = self._shutdown = None
        self._sessions.clear()
        self._tools.clear()

    def list_tools(self) -> Sequence[DiscoveredTool]:
        self._require_started()
        return tuple(self._tools)

    def call_tool(self, server: str, name: str, arguments: Mapping[str, Any]) -> str:
        loop = self._require_started()
        session = self._sessions[server]
        coro = session.call_tool(
            name, dict(arguments), read_timeout_seconds=timedelta(seconds=self._call_timeout)
        )
        try:
            result = asyncio.run_coroutine_threadsafe(coro, loop).result()
        except Exception as exc:  # transport faults become an observation, not a crash
            raise McpToolError(f"call to {name!r} failed: {exc}") from exc
        return _render(result)

    async def _caretake(self, ready: Future[None]) -> None:
        try:
            async with AsyncExitStack() as stack:
                for name, connect in self._connectors.items():
                    session = await stack.enter_async_context(connect())
                    self._sessions[name] = session
                    await self._discover(name, session)
                self._shutdown = asyncio.Event()
                ready.set_result(None)
                await self._shutdown.wait()
        except BaseException as exc:  # surface connection failures to start()
            if not ready.done():
                ready.set_exception(exc)

    async def _discover(self, server: str, session: ClientSession) -> None:
        for tool in (await session.list_tools()).tools:
            self._tools.append(
                DiscoveredTool(
                    server=server,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or _EMPTY_SCHEMA,
                    mutating=_is_mutating(tool.annotations),
                )
            )

    def _require_started(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("MCP host is not started")
        return self._loop


def _is_mutating(annotations: ToolAnnotations | None) -> bool:
    # A tool counts as mutating only when it declares a write; absent hints mean
    # read-only, so the Phase-4 gate stays reserved for genuine side effects
    # rather than desensitizing the user to prompts on every lookup.
    if annotations is None:
        return False
    if annotations.destructiveHint:
        return True
    return annotations.readOnlyHint is False


def _render(result: CallToolResult) -> str:
    body = "\n".join(
        block.text if isinstance(block, TextContent) else f"[{block.type}]"
        for block in result.content
    ).strip()
    if result.isError:
        raise McpToolError(body or "tool reported an error")
    return body or "(no output)"
