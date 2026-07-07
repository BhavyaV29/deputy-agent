"""Tool registry, schema helper, and signature rendering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from deputy.tools import Tool, ToolRegistry, object_schema, signature


def _noop(args: Mapping[str, Any]) -> str:
    return "ok"


def test_register_get_and_membership() -> None:
    tool = Tool("x", "d", object_schema(), _noop)
    registry = ToolRegistry([tool])
    assert "x" in registry
    assert registry.get("x") is tool
    assert registry.names() == ["x"]
    assert len(registry) == 1
    assert list(registry) == [tool]


def test_duplicate_name_is_rejected() -> None:
    registry = ToolRegistry([Tool("x", "d", object_schema(), _noop)])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("x", "other", object_schema(), _noop))


def test_get_unknown_raises() -> None:
    with pytest.raises(KeyError):
        ToolRegistry().get("nope")


def test_object_schema_marks_all_properties_required() -> None:
    schema = object_schema(a={"type": "string"}, b={"type": "string"})
    assert schema["type"] == "object"
    assert schema["required"] == ["a", "b"]
    assert schema["additionalProperties"] is False


def test_signature_lists_typed_params() -> None:
    tool = Tool("calc", "d", object_schema(expression={"type": "string"}), _noop)
    assert signature(tool) == "calc(expression: string)"


def test_signature_of_no_arg_tool() -> None:
    assert signature(Tool("now", "d", object_schema(), _noop)) == "now()"
