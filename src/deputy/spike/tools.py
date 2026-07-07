"""The fixed tool set the spike routes to.

The registry below is the single source of truth: the JSON Schema used for
constrained decoding, the instructions shown to the model, and the validator
are all derived from it, so they cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: Mapping[str, str]  # argument name -> JSON Schema type


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "search_files",
        "Search the user's files for a phrase or topic and list the matches.",
        {"query": "string"},
    ),
    ToolSpec(
        "read_file",
        "Read the full contents of a single file at a given path.",
        {"path": "string"},
    ),
    ToolSpec(
        "add_note",
        "Save a short note for the user.",
        {"text": "string"},
    ),
    ToolSpec(
        "get_calendar",
        "Look up the user's calendar entries for a given date.",
        {"date": "string"},
    ),
)

TOOLS_BY_NAME: Mapping[str, ToolSpec] = {tool.name: tool for tool in TOOLS}


def signature(tool: ToolSpec) -> str:
    params = ", ".join(f"{name}: {kind}" for name, kind in tool.args.items())
    return f"{tool.name}({params})"


def system_prompt(tools: Sequence[ToolSpec] = TOOLS) -> str:
    # Intentionally a realistic instruction rather than a heavily coercive one
    # ("emit only JSON, no prose, no fences, ..."). Over-coaching the prompt is
    # itself a workaround for unconstrained decoding and would mask the very gap
    # this spike measures, so we describe the contract plainly and let the
    # `format` schema — not prompt engineering — be what guarantees validity.
    catalog = "\n".join(f"- {signature(tool)}: {tool.description}" for tool in tools)
    return (
        "You are Deputy, a private on-device assistant with access to these tools:\n"
        f"{catalog}\n\n"
        "Choose the single most appropriate tool for the user's request and reply with the "
        'call as a JSON object of the form {"tool": "<name>", "args": {...}}, using only that '
        "tool's arguments."
    )


def tool_call_schema(tools: Sequence[ToolSpec] = TOOLS) -> dict[str, Any]:
    """Union schema that admits a well-formed call to any one tool."""
    return {"anyOf": [_tool_branch(tool) for tool in tools]}


def _tool_branch(tool: ToolSpec) -> dict[str, Any]:
    arg_properties = {name: {"type": kind} for name, kind in tool.args.items()}
    return {
        "type": "object",
        "properties": {
            "tool": {"const": tool.name},
            "args": {
                "type": "object",
                "properties": arg_properties,
                "required": list(tool.args),
                "additionalProperties": False,
            },
        },
        "required": ["tool", "args"],
        "additionalProperties": False,
    }
