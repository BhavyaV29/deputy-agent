"""The bounded ReAct loop, driven by a scripted fake model (no Ollama)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from deputy.actions import ActionParseError, ToolCall
from deputy.agent import Agent, AgentConfig
from deputy.approvals import ApprovalDecision
from deputy.critic import CriticResult
from deputy.events import ActionDenied, AnswerRejected, Event, StopReason, ToolObserved
from deputy.model import ChatResponse, Message
from deputy.tools import Tool, ToolRegistry, object_schema


class ScriptedModel:
    """A ChatModel that replays canned replies and records every prompt it sees."""

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


def tool_call(tool: str, **args: Any) -> str:
    return json.dumps({"tool": tool, "args": args})


def final(text: str) -> str:
    return json.dumps({"final": text})


def make_registry(recorder: list[str]) -> ToolRegistry:
    def remember(args: Mapping[str, Any]) -> str:
        recorder.append(str(args["text"]))
        return f"stored: {args['text']}"

    def explode(args: Mapping[str, Any]) -> str:
        raise RuntimeError("boom")

    return ToolRegistry(
        [
            Tool("remember", "store text", object_schema(text={"type": "string"}), remember),
            Tool("explode", "always fails", object_schema(), explode),
        ]
    )


def _contents(messages: Sequence[Message]) -> str:
    return "\n".join(m.content for m in messages)


def test_runs_tool_then_finishes_and_threads_the_observation() -> None:
    recorder: list[str] = []
    model = ScriptedModel([tool_call("remember", text="milk"), final("all set")])

    result = Agent(model, make_registry(recorder)).run("remember milk")

    assert result.answer == "all set"
    assert result.reason is StopReason.ANSWERED
    assert result.steps == 2
    assert recorder == ["milk"]
    # The second prompt must carry the first step's observation back to the model.
    assert "stored: milk" in _contents(model.calls[1])


def test_step_ceiling_stops_a_non_terminating_loop() -> None:
    model = ScriptedModel([tool_call("remember", text="x")] * 10)

    result = Agent(model, make_registry([]), config=AgentConfig(max_steps=3)).run("go")

    assert result.answer is None
    assert result.reason is StopReason.MAX_STEPS
    assert result.steps == 3
    assert len(model.calls) == 3


def test_tool_exception_becomes_an_observation_and_the_loop_continues() -> None:
    model = ScriptedModel([tool_call("explode"), final("recovered")])

    result = Agent(model, make_registry([])).run("go")

    assert result.answer == "recovered"
    observed = next(e for e in result.events if isinstance(e, ToolObserved))
    assert observed.ok is False
    assert "RuntimeError" in observed.observation
    assert "RuntimeError" in _contents(model.calls[1])


def test_default_approval_lets_the_tool_run() -> None:
    recorder: list[str] = []
    model = ScriptedModel([tool_call("remember", text="hi"), final("ok")])

    Agent(model, make_registry(recorder)).run("go")

    assert recorder == ["hi"]


def test_denied_action_is_not_executed_and_is_fed_back() -> None:
    recorder: list[str] = []
    model = ScriptedModel([tool_call("remember", text="secret"), final("ok")])

    def deny(call: ToolCall) -> ApprovalDecision:
        return ApprovalDecision(approved=False, reason="not allowed")

    result = Agent(model, make_registry(recorder), approve=deny).run("go")

    assert recorder == []  # the handler never ran
    assert result.answer == "ok"
    denied = [e for e in result.events if isinstance(e, ActionDenied)]
    assert len(denied) == 1
    assert denied[0].reason == "not allowed"
    assert "declined" in _contents(model.calls[1])


def test_event_stream_matches_the_transitions() -> None:
    model = ScriptedModel([tool_call("remember", text="a"), final("z")])
    seen: list[Event] = []

    result = Agent(model, make_registry([]), on_event=seen.append).run("go")

    assert [type(e).__name__ for e in seen] == [
        "ActionPlanned",
        "ToolObserved",
        "ActionPlanned",
        "RunFinished",
    ]
    assert seen == list(result.events)


def test_no_critic_accepts_the_first_final_answer() -> None:
    model = ScriptedModel([final("first")])

    result = Agent(model, make_registry([])).run("go")

    assert result.answer == "first"
    assert result.steps == 1


def test_critic_can_reject_once_then_accept() -> None:
    model = ScriptedModel([final("draft"), final("revised")])
    verdicts = iter([CriticResult(False, "too short"), CriticResult(True)])

    def critic(goal: str, answer: str) -> CriticResult:
        return next(verdicts)

    result = Agent(model, make_registry([]), critic=critic).run("go")

    assert result.answer == "revised"
    assert result.steps == 2
    rejected = [e for e in result.events if isinstance(e, AnswerRejected)]
    assert len(rejected) == 1
    assert rejected[0].feedback == "too short"
    assert "too short" in _contents(model.calls[1])


def test_unparseable_output_surfaces_as_an_error() -> None:
    model = ScriptedModel(["definitely not json"])
    with pytest.raises(ActionParseError):
        Agent(model, make_registry([])).run("go")


def test_empty_registry_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one tool"):
        Agent(ScriptedModel([]), ToolRegistry())


def test_max_steps_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_steps"):
        AgentConfig(max_steps=0)
