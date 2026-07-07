"""The generated schema and prompt should stay in step with the tool registry."""

from __future__ import annotations

from deputy.spike.tools import TOOLS, system_prompt, tool_call_schema


def test_schema_has_one_branch_per_tool() -> None:
    schema = tool_call_schema()
    branches = schema["anyOf"]
    assert len(branches) == len(TOOLS)


def test_each_branch_pins_the_tool_name_and_requires_its_args() -> None:
    branches = {b["properties"]["tool"]["const"]: b for b in tool_call_schema()["anyOf"]}
    for tool in TOOLS:
        branch = branches[tool.name]
        assert branch["required"] == ["tool", "args"]
        args_schema = branch["properties"]["args"]
        assert args_schema["required"] == list(tool.args)
        assert args_schema["additionalProperties"] is False


def test_system_prompt_lists_every_tool_and_the_json_shape() -> None:
    prompt = system_prompt()
    for tool in TOOLS:
        assert tool.name in prompt
    assert '"tool"' in prompt and '"args"' in prompt
