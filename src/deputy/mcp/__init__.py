"""MCP integration: connect to servers, discover tools, adapt them for the loop.

The agent core knows nothing about MCP. This package bridges the two worlds —
it speaks the SDK's async protocol to real servers and hands the loop plain
synchronous :class:`~deputy.tools.Tool` objects, so a tool sourced over MCP is
indistinguishable from a native one once it lands in the registry.
"""

from __future__ import annotations

from deputy.mcp.adapter import ToolSource, register_mcp_tools
from deputy.mcp.host import (
    Connector,
    DiscoveredTool,
    McpHost,
    McpToolError,
    ServerSpec,
    memory_connector,
    stdio_connector,
)

__all__ = [
    "Connector",
    "DiscoveredTool",
    "McpHost",
    "McpToolError",
    "ServerSpec",
    "ToolSource",
    "memory_connector",
    "register_mcp_tools",
    "stdio_connector",
]
