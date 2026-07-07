"""The synchronous host, driven against an in-memory MCP server (no subprocess)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from deputy.mcp import McpHost, McpToolError, memory_connector


def _fixture_server() -> FastMCP:
    server = FastMCP("fixture")

    @server.tool(
        name="greet",
        description="Greet someone by name.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def greet(name: str) -> str:
        return f"hello {name}"

    @server.tool(
        name="save",
        description="Persist a value.",
        annotations=ToolAnnotations(readOnlyHint=False),
    )
    def save(value: str) -> str:
        return f"saved {value}"

    @server.tool(name="boom", description="Always fails.")
    def boom() -> str:
        raise RuntimeError("nope")

    return server


@pytest.fixture
def host() -> Iterator[McpHost]:
    with McpHost({"fixture": memory_connector(_fixture_server())}) as started:
        yield started


def test_discovers_tools_with_names_schema_and_description(host: McpHost) -> None:
    tools = {tool.name: tool for tool in host.list_tools()}
    assert set(tools) == {"greet", "save", "boom"}
    assert tools["greet"].description == "Greet someone by name."
    assert tools["greet"].input_schema["properties"]["name"]["type"] == "string"


def test_read_only_hint_maps_to_the_mutating_flag(host: McpHost) -> None:
    tools = {tool.name: tool for tool in host.list_tools()}
    assert tools["greet"].mutating is False
    assert tools["save"].mutating is True
    assert tools["boom"].mutating is False  # no hint at all -> treated as read-only


def test_call_returns_a_text_observation(host: McpHost) -> None:
    assert host.call_tool("fixture", "greet", {"name": "Ada"}) == "hello Ada"


def test_a_failing_tool_surfaces_as_an_error(host: McpHost) -> None:
    with pytest.raises(McpToolError):
        host.call_tool("fixture", "boom", {})


def test_methods_require_a_started_host() -> None:
    host = McpHost({"fixture": memory_connector(_fixture_server())})
    with pytest.raises(RuntimeError, match="not started"):
        host.list_tools()


def test_start_and_stop_are_idempotent() -> None:
    host = McpHost({"fixture": memory_connector(_fixture_server())})
    host.start()
    host.start()  # second start is a no-op
    assert len(host.list_tools()) == 3
    host.stop()
    host.stop()  # second stop is a no-op
