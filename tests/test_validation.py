"""Unit tests for the tool-call schema validator (no live model required)."""

from __future__ import annotations

import json

import pytest

from deputy.spike.tools import TOOLS, ToolSpec
from deputy.spike.validation import check_tool_call


def _valid_payload(tool: ToolSpec) -> str:
    return json.dumps({"tool": tool.name, "args": {name: "x" for name in tool.args}})


@pytest.mark.parametrize("tool", TOOLS, ids=[tool.name for tool in TOOLS])
def test_well_formed_call_for_every_tool_is_valid(tool: ToolSpec) -> None:
    result = check_tool_call(_valid_payload(tool))
    assert result.schema_valid
    assert result.tool == tool.name
    assert result.error is None


def test_ignores_surrounding_whitespace() -> None:
    assert check_tool_call('  {"tool": "add_note", "args": {"text": "hi"}}\n').schema_valid


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json at all",
        "{tool: add_note}",
        '```json\n{"tool": "add_note", "args": {"text": "hi"}}\n```',
    ],
)
def test_non_json_is_invalid(raw: str) -> None:
    result = check_tool_call(raw)
    assert not result.schema_valid
    assert result.tool is None


@pytest.mark.parametrize("raw", ["[1, 2, 3]", '"add_note"', "42", "null"])
def test_non_object_json_is_invalid(raw: str) -> None:
    result = check_tool_call(raw)
    assert not result.schema_valid
    assert result.tool is None


def test_unknown_tool_is_invalid_but_name_is_captured() -> None:
    result = check_tool_call('{"tool": "delete_everything", "args": {}}')
    assert not result.schema_valid
    assert result.tool == "delete_everything"


def test_non_string_tool_yields_no_captured_name() -> None:
    result = check_tool_call('{"tool": 7, "args": {}}')
    assert not result.schema_valid
    assert result.tool is None


def test_missing_args_key_is_invalid() -> None:
    result = check_tool_call('{"tool": "add_note"}')
    assert not result.schema_valid
    assert result.tool == "add_note"


def test_extra_top_level_key_is_invalid() -> None:
    raw = '{"tool": "add_note", "args": {"text": "hi"}, "confidence": 0.9}'
    result = check_tool_call(raw)
    assert not result.schema_valid
    assert result.tool == "add_note"


def test_args_must_be_an_object() -> None:
    assert not check_tool_call('{"tool": "add_note", "args": "hi"}').schema_valid


def test_wrong_argument_name_is_invalid() -> None:
    assert not check_tool_call('{"tool": "read_file", "args": {"file": "a.txt"}}').schema_valid


def test_extra_argument_is_invalid() -> None:
    raw = '{"tool": "read_file", "args": {"path": "a.txt", "mode": "r"}}'
    assert not check_tool_call(raw).schema_valid


def test_wrong_argument_type_is_invalid() -> None:
    assert not check_tool_call('{"tool": "search_files", "args": {"query": 123}}').schema_valid


def test_captures_tool_name_when_only_arguments_are_wrong() -> None:
    result = check_tool_call('{"tool": "search_files", "args": {"query": 123}}')
    assert not result.schema_valid
    assert result.tool == "search_files"
