"""In-process tools and a name -> tool registry.

The registry is the single source of truth that the action schema and the system
prompt are both derived from, so the model can only ever be offered tools that
actually exist.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

ToolHandler = Callable[[Mapping[str, Any]], str]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Mapping[str, Any]  # JSON Schema for the tool's args object
    handler: ToolHandler
    mutating: bool = False  # writes/side effects; Phase 4 gates these selectively


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool {name!r}") from None

    def names(self) -> list[str]:
        return list(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def object_schema(**properties: Mapping[str, Any]) -> dict[str, Any]:
    """JSON Schema for an object whose listed properties are all required."""
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def signature(tool: Tool) -> str:
    props = tool.parameters.get("properties", {})
    params = ", ".join(f"{name}: {spec.get('type', 'any')}" for name, spec in props.items())
    return f"{tool.name}({params})"
