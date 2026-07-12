"""The synchronous host, driven against an in-memory MCP server (no subprocess)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from deputy.actions import ToolCall
from deputy.approvals import ApprovalDecision, ApprovalRequest, policy_approver
from deputy.mcp import McpHost, McpToolError, memory_connector, register_mcp_tools
from deputy.tools import ApprovalRisk, ToolRegistry


def _fixture_server() -> FastMCP:
    server = FastMCP("fixture")

    @server.tool(
        name="greet",
        description="Greet someone by name.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def greet(name: str) -> str:
        return f"hello {name}"

    @server.tool(
        name="save",
        description="Persist a value.",
        annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    )
    def save(value: str) -> str:
        return f"saved {value}"

    @server.tool(
        name="browse",
        description="Look something up remotely.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    )
    def browse(query: str) -> str:
        return f"remote {query}"

    @server.tool(
        name="ambiguous",
        description="Read without declaring confinement.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    def ambiguous() -> str:
        return "maybe local"

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
    assert set(tools) == {"greet", "save", "browse", "ambiguous", "boom"}
    assert tools["greet"].description == "Greet someone by name."
    assert tools["greet"].input_schema["properties"]["name"]["type"] == "string"


def test_annotations_map_to_mutation_and_approval_risk(host: McpHost) -> None:
    tools = {tool.name: tool for tool in host.list_tools()}
    assert tools["greet"].mutating is False
    assert tools["greet"].approval_risk is ApprovalRisk.LOCAL_READ
    assert tools["save"].mutating is True
    assert tools["save"].approval_risk is ApprovalRisk.MUTATION
    assert tools["browse"].mutating is False
    assert tools["browse"].approval_risk is ApprovalRisk.EXTERNAL
    assert tools["ambiguous"].approval_risk is ApprovalRisk.UNKNOWN
    assert tools["boom"].mutating is False
    assert tools["boom"].approval_risk is ApprovalRisk.UNKNOWN


def test_discovered_missing_ambiguous_and_external_risks_require_approval(
    host: McpHost,
) -> None:
    registry = ToolRegistry()
    register_mcp_tools(host, registry)
    prompted: list[ApprovalRequest] = []

    def deny(request: ApprovalRequest) -> ApprovalDecision:
        prompted.append(request)
        return ApprovalDecision(False, "test denial")

    approve = policy_approver(registry, deny)

    assert approve(ToolCall("greet", {"name": "Ada"})).approved is True
    assert approve(ToolCall("browse", {"query": "Ada"})).approved is False
    assert approve(ToolCall("ambiguous", {})).approved is False
    assert approve(ToolCall("boom", {})).approved is False
    assert [request.risk for request in prompted] == [
        ApprovalRisk.EXTERNAL,
        ApprovalRisk.UNKNOWN,
        ApprovalRisk.UNKNOWN,
    ]


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
    assert len(host.list_tools()) == 5
    host.stop()
    host.stop()  # second stop is a no-op
