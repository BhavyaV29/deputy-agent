"""Trivial in-process tools used to exercise the loop end to end.

Real tools (MCP) and retrieval arrive in Phase 3; these exist only so the loop
can be driven against a live model today.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from deputy.tools import Tool, ToolRegistry, object_schema

_BINARY_OPS: Mapping[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Mapping[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return float(_BINARY_OPS[type(node.op)](_eval(node.left), _eval(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_eval(node.operand)))
    raise ValueError("unsupported expression")


def _calculate(args: Mapping[str, Any]) -> str:
    expression = str(args["expression"])
    try:
        value = _eval(ast.parse(expression, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
        raise ValueError(f"cannot evaluate {expression!r}: {exc}") from exc
    return f"{value:g}"


def _current_time(args: Mapping[str, Any]) -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _echo(args: Mapping[str, Any]) -> str:
    return str(args["text"])


CALCULATOR = Tool(
    "calculator",
    "Evaluate a basic arithmetic expression (+, -, *, /, %, **).",
    object_schema(expression={"type": "string", "description": "e.g. '3 * (4 + 1)'"}),
    _calculate,
)
CURRENT_TIME = Tool(
    "current_time",
    "Return the current UTC time in ISO-8601 format.",
    object_schema(),
    _current_time,
)
ECHO = Tool(
    "echo",
    "Repeat the given text back verbatim.",
    object_schema(text={"type": "string"}),
    _echo,
)


def demo_registry() -> ToolRegistry:
    return ToolRegistry([CALCULATOR, CURRENT_TIME, ECHO])
