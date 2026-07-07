"""The model's per-step decision: call a tool or finish.

Every step is constrained to :func:`action_schema` — a JSON union of one branch
per tool (name pinned, args typed to that tool) plus a final-answer branch — so
:func:`parse_action` can always recover a typed :data:`Action` from the output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from deputy.tools import Tool, ToolRegistry


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class FinalAnswer:
    text: str


Action = ToolCall | FinalAnswer


class ActionParseError(ValueError):
    """Model output did not match the action schema."""


def action_schema(registry: ToolRegistry) -> dict[str, Any]:
    branches = [_tool_branch(tool) for tool in registry]
    branches.append(_final_branch())
    return {"anyOf": branches}


def _tool_branch(tool: Tool) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"tool": {"const": tool.name}, "args": dict(tool.parameters)},
        "required": ["tool", "args"],
        "additionalProperties": False,
    }


def _final_branch() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"final": {"type": "string"}},
        "required": ["final"],
        "additionalProperties": False,
    }


def parse_action(raw: str, registry: ToolRegistry) -> Action:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"output is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ActionParseError("action must be a JSON object")

    keys = set(payload)
    if keys == {"final"}:
        return _final(payload["final"])
    if keys == {"tool", "args"}:
        return _tool_call(payload["tool"], payload["args"], registry)
    raise ActionParseError(
        "action keys must be {'tool', 'args'} or {'final'}, got " + repr(sorted(keys))
    )


def _final(text: object) -> FinalAnswer:
    if not isinstance(text, str):
        raise ActionParseError("'final' must be a string")
    return FinalAnswer(text)


def _tool_call(name: object, args: object, registry: ToolRegistry) -> ToolCall:
    if not isinstance(name, str):
        raise ActionParseError("'tool' must be a string")
    if name not in registry:
        raise ActionParseError(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise ActionParseError("'args' must be an object")
    return ToolCall(tool=name, args=args)
