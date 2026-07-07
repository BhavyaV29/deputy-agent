"""Schema validation for tool-call payloads.

This mirrors the JSON Schema fed to Ollama's constrained decoder, but as plain
Python so it can be unit-tested without a running model. A payload is valid iff
it is a JSON object of exactly ``{"tool", "args"}`` where ``tool`` names a known
tool and ``args`` carries exactly that tool's arguments with the right types.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from deputy.spike.tools import TOOLS_BY_NAME, ToolSpec

_PYTHON_TYPES: Mapping[str, type] = {"string": str}


@dataclass(frozen=True)
class ToolCallCheck:
    schema_valid: bool
    tool: str | None  # captured whenever a string "tool" is present, even if the call is invalid
    error: str | None = None


def check_tool_call(raw: str, tools: Mapping[str, ToolSpec] = TOOLS_BY_NAME) -> ToolCallCheck:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ToolCallCheck(False, None, "output is not valid JSON")

    if not isinstance(payload, dict):
        return ToolCallCheck(False, None, "top-level value is not an object")

    raw_tool = payload.get("tool")
    tool = raw_tool if isinstance(raw_tool, str) else None

    if set(payload) != {"tool", "args"}:
        return ToolCallCheck(False, tool, "object must have exactly the keys 'tool' and 'args'")
    if tool is None:
        return ToolCallCheck(False, None, "'tool' must be a string")

    spec = tools.get(tool)
    if spec is None:
        return ToolCallCheck(False, tool, f"unknown tool {tool!r}")

    args = payload["args"]
    if not isinstance(args, dict):
        return ToolCallCheck(False, tool, "'args' must be an object")
    if set(args) != set(spec.args):
        return ToolCallCheck(False, tool, "argument keys do not match the tool signature")

    for name, kind in spec.args.items():
        if not isinstance(args[name], _PYTHON_TYPES[kind]):
            return ToolCallCheck(False, tool, f"argument {name!r} must be a {kind}")

    return ToolCallCheck(True, tool)
