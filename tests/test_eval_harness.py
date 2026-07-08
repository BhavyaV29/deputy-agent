"""The runner: agent wiring, trace extraction, gating, and failure capture."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from deputy.eval.environment import ADD_NOTE, CALCULATOR, SEARCH_DOCS, SEARCH_NOTES
from deputy.eval.grading import answer_contains, answered, did_not_execute, gated, used_tool
from deputy.eval.harness import run_config, run_task
from deputy.eval.model import DecodingMode
from deputy.eval.spec import EvalConfig, Task, TaskCategory
from deputy.eval.suite import TASK_SUITE
from deputy.model import ChatResponse, Message

SUITE = {task.id: task for task in TASK_SUITE}


class ScriptedByGoal:
    """Replays per-goal scripts, indexing by how many steps the loop has taken."""

    def __init__(self, scripts: Mapping[str, Sequence[str]]) -> None:
        self._scripts = scripts

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        goal = next(m.content for m in messages if m.role == "user")
        step = sum(m.role == "assistant" for m in messages)
        replies = self._scripts[goal]
        text = replies[min(step, len(replies) - 1)]
        return ChatResponse(text, eval_count=8, eval_duration_ns=10**9)


def _call(tool: str, **args: Any) -> str:
    return json.dumps({"tool": tool, "args": args})


def _final(text: str) -> str:
    return json.dumps({"final": text})


def _config(mode: DecodingMode = DecodingMode.GRAMMAR) -> EvalConfig:
    return EvalConfig(model="fake", mode=mode)


def test_happy_path_scores_success_and_records_the_trace() -> None:
    task = Task(
        id="calc",
        prompt="double it",
        category=TaskCategory.TOOL_SELECTION,
        tools=(CALCULATOR, SEARCH_DOCS),
        expected_tools=frozenset({CALCULATOR}),
        checks=(answered(), answer_contains("42")),
    )
    model = ScriptedByGoal(
        {"double it": [_call(CALCULATOR, expression="21 * 2"), _final("the answer is 42")]}
    )

    result = run_task(model, task, _config())

    assert result.success is True
    assert result.selection_correct is True
    assert result.run.planned_tools == (CALCULATOR,)
    assert result.run.executed_tools == (CALCULATOR,)
    assert result.run.answer == "the answer is 42"
    assert len(result.run.telemetry) == 2
    assert all(call.schema_valid for call in result.run.telemetry)


def test_mutating_call_is_gated_and_never_executes() -> None:
    task = Task(
        id="note",
        prompt="remember this",
        category=TaskCategory.APPROVAL_GATING,
        tools=(ADD_NOTE, SEARCH_NOTES),
        expected_tools=frozenset({ADD_NOTE}),
        checks=(
            used_tool(ADD_NOTE),
            gated(ADD_NOTE),
            did_not_execute(ADD_NOTE),
        ),
        max_steps=3,
    )
    model = ScriptedByGoal({"remember this": [_call(ADD_NOTE, text="buy milk"), _final("noted")]})

    result = run_task(model, task, _config())

    assert result.success is True
    assert result.run.gated_mutations == (ADD_NOTE,)
    assert result.run.executed_tools == ()
    assert result.run.denied_tools == (ADD_NOTE,)
    assert result.run.mutating_attempts == 1
    assert result.run.ungated_mutations == ()


def test_unparseable_step_is_caught_as_failure_and_marked_invalid() -> None:
    task = Task(
        id="bad",
        prompt="freeform please",
        category=TaskCategory.TOOL_SELECTION,
        tools=(CALCULATOR,),
        expected_tools=frozenset(),
        checks=(answered(),),
    )
    model = ScriptedByGoal({"freeform please": ["not json at all"]})

    result = run_task(model, task, _config(DecodingMode.FREEFORM))

    assert result.success is False
    assert result.run.error is not None
    assert result.run.answer is None
    assert result.run.telemetry[0].schema_valid is False


def test_hallucinated_unknown_tool_fails_the_task() -> None:
    task = Task(
        id="ghost",
        prompt="call a ghost",
        category=TaskCategory.TOOL_SELECTION,
        tools=(CALCULATOR,),
        expected_tools=frozenset({CALCULATOR}),
        checks=(answered(),),
    )
    model = ScriptedByGoal({"call a ghost": [json.dumps({"tool": "ghost", "args": {}})]})

    result = run_task(model, task, _config(DecodingMode.FREEFORM))

    assert result.success is False
    assert result.run.error is not None


def test_selection_is_wrong_when_the_expected_tool_is_skipped() -> None:
    task = Task(
        id="skip",
        prompt="answer directly",
        category=TaskCategory.TOOL_SELECTION,
        tools=(CALCULATOR,),
        expected_tools=frozenset({CALCULATOR}),
        checks=(answered(),),
    )
    model = ScriptedByGoal({"answer directly": [_final("no tool needed")]})

    result = run_task(model, task, _config())

    assert result.success is True  # it did answer
    assert result.selection_correct is False  # but skipped the expected tool
    assert result.run.planned_tools == ()


def test_run_config_runs_every_task_and_reports_progress() -> None:
    tasks = (
        Task(
            id="a",
            prompt="a",
            category=TaskCategory.TOOL_SELECTION,
            tools=(CALCULATOR,),
            expected_tools=frozenset(),
            checks=(answered(),),
        ),
        Task(
            id="b",
            prompt="b",
            category=TaskCategory.TOOL_SELECTION,
            tools=(CALCULATOR,),
            expected_tools=frozenset(),
            checks=(answered(),),
        ),
    )
    model = ScriptedByGoal({"a": [_final("done a")], "b": [_final("done b")]})
    seen: list[str] = []

    result = run_config(model, _config(), tasks, on_result=lambda r: seen.append(r.task.id))

    assert seen == ["a", "b"]
    assert [r.task.id for r in result.results] == ["a", "b"]
    assert all(r.success for r in result.results)


def test_real_suite_task_grades_through_the_harness() -> None:
    task = SUITE["rag_vacation"]
    model = ScriptedByGoal(
        {task.prompt: [_call(SEARCH_DOCS, query="vacation policy"), _final("You get 15 per year.")]}
    )

    result = run_task(model, task, _config())

    assert result.success is True
    assert result.selection_correct is True
    assert result.run.executed_tools == (SEARCH_DOCS,)
