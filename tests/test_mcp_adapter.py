"""Adapting discovered MCP tools into the registry and running them from the loop."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from deputy.agent import Agent
from deputy.mcp import DiscoveredTool, register_mcp_tools
from deputy.model import ChatResponse, Message
from deputy.tools import ApprovalRisk, ToolRegistry

_TOOLS = [
    DiscoveredTool(
        server="files",
        name="search_files",
        description="Search files.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        mutating=False,
        approval_risk=ApprovalRisk.LOCAL_READ,
    ),
    DiscoveredTool(
        server="notes",
        name="add_note",
        description="Save a note.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        mutating=True,
        approval_risk=ApprovalRisk.MUTATION,
    ),
]


class FakeSource:
    def __init__(self, replies: Mapping[str, str] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._replies = dict(replies or {})

    def list_tools(self) -> Sequence[DiscoveredTool]:
        return _TOOLS

    def call_tool(self, server: str, name: str, arguments: Mapping[str, Any]) -> str:
        self.calls.append((server, name, dict(arguments)))
        return self._replies.get(name, f"{name}: ok")


class ScriptedModel:
    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return ChatResponse(self._replies[len(self.calls) - 1])


def test_adapts_name_description_schema_and_mutating() -> None:
    registry = ToolRegistry()
    added = register_mcp_tools(FakeSource(), registry)

    assert [tool.name for tool in added] == ["search_files", "add_note"]
    search = registry.get("search_files")
    assert search.description == "Search files."
    assert search.parameters["required"] == ["query"]
    assert search.mutating is False
    assert search.approval_risk is ApprovalRisk.LOCAL_READ
    add_note = registry.get("add_note")
    assert add_note.mutating is True
    assert add_note.approval_risk is ApprovalRisk.MUTATION


def test_handler_dispatches_back_through_the_source() -> None:
    source = FakeSource({"search_files": "match: deputy.md"})
    registry = ToolRegistry()
    register_mcp_tools(source, registry)

    observation = registry.get("search_files").handler({"query": "deputy"})

    assert observation == "match: deputy.md"
    assert source.calls == [("files", "search_files", {"query": "deputy"})]


def test_the_phase2_loop_drives_an_adapted_tool() -> None:
    source = FakeSource({"search_files": "match in deputy.md"})
    registry = ToolRegistry()
    register_mcp_tools(source, registry)
    model = ScriptedModel(
        [
            json.dumps({"tool": "search_files", "args": {"query": "deputy"}}),
            json.dumps({"final": "It's mentioned in deputy.md."}),
        ]
    )

    result = Agent(model, registry).run("where is deputy mentioned?")

    assert result.answer == "It's mentioned in deputy.md."
    assert source.calls == [("files", "search_files", {"query": "deputy"})]
    threaded_back = "\n".join(m.content for m in model.calls[1])
    assert "match in deputy.md" in threaded_back
