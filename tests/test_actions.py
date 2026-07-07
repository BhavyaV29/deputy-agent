"""Constrained action schema construction and parsing."""

from __future__ import annotations

import pytest

from deputy.actions import ActionParseError, FinalAnswer, ToolCall, action_schema, parse_action
from deputy.demo import demo_registry


def test_schema_has_one_branch_per_tool_plus_a_final_branch() -> None:
    registry = demo_registry()
    branches = action_schema(registry)["anyOf"]
    assert len(branches) == len(registry) + 1

    final_branches = [b for b in branches if list(b["properties"]) == ["final"]]
    assert len(final_branches) == 1
    assert final_branches[0]["properties"]["final"] == {"type": "string"}

    tool_consts = {b["properties"]["tool"]["const"] for b in branches if "tool" in b["properties"]}
    assert tool_consts == set(registry.names())


def test_tool_branch_pins_name_and_args_schema() -> None:
    branches = {
        b["properties"]["tool"]["const"]: b
        for b in action_schema(demo_registry())["anyOf"]
        if "tool" in b["properties"]
    }
    calc = branches["calculator"]
    assert calc["required"] == ["tool", "args"]
    assert calc["additionalProperties"] is False
    assert calc["properties"]["args"]["required"] == ["expression"]
    assert calc["properties"]["args"]["additionalProperties"] is False


def test_parse_tool_call() -> None:
    action = parse_action('{"tool": "echo", "args": {"text": "hi"}}', demo_registry())
    assert action == ToolCall("echo", {"text": "hi"})


def test_parse_final_answer() -> None:
    assert parse_action('{"final": "done"}', demo_registry()) == FinalAnswer("done")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[1, 2, 3]",
        '"echo"',
        '{"tool": "echo"}',  # missing args
        '{"final": 1}',  # final not a string
        '{"tool": "nope", "args": {}}',  # unknown tool
        '{"tool": 7, "args": {}}',  # tool not a string
        '{"tool": "echo", "args": "x"}',  # args not an object
        '{"tool": "echo", "args": {}, "note": 1}',  # extra key
        '{"other": 1}',  # neither shape
    ],
)
def test_parse_rejects_malformed_actions(raw: str) -> None:
    with pytest.raises(ActionParseError):
        parse_action(raw, demo_registry())
