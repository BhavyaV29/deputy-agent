"""Adapt discovered MCP tools into native :class:`~deputy.tools.Tool` objects.

The mapping is deliberately total and mechanical: an MCP tool's name, description,
and input schema become the Deputy tool's, its read-only hint becomes the
``mutating`` flag, and its handler is a thin closure that dispatches the call back
through the host. Once registered, the constrained action schema and system prompt
pick it up with no further plumbing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from deputy.mcp.host import DiscoveredTool
from deputy.tools import Tool, ToolRegistry


class ToolSource(Protocol):
    def list_tools(self) -> Sequence[DiscoveredTool]: ...
    def call_tool(self, server: str, name: str, arguments: Mapping[str, Any]) -> str: ...


def register_mcp_tools(source: ToolSource, registry: ToolRegistry) -> list[Tool]:
    tools = [_adapt(source, discovered) for discovered in source.list_tools()]
    for tool in tools:
        registry.register(tool)
    return tools


def _adapt(source: ToolSource, discovered: DiscoveredTool) -> Tool:
    def handler(args: Mapping[str, Any]) -> str:
        return source.call_tool(discovered.server, discovered.name, args)

    return Tool(
        name=discovered.name,
        description=discovered.description,
        parameters=_args_schema(discovered.input_schema),
        handler=handler,
        mutating=discovered.mutating,
    )


def _args_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    if schema.get("type") == "object":
        return dict(schema)
    return {"type": "object", "properties": {}, "additionalProperties": False}
