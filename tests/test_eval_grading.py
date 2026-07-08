"""The deterministic grader primitives."""

from __future__ import annotations

from typing import Any

from deputy.eval import grading
from deputy.eval.spec import TaskRun
from deputy.events import StopReason


def make_run(**overrides: Any) -> TaskRun:
    defaults: dict[str, Any] = {
        "task_id": "t",
        "prompt": "p",
        "answer": "the answer is 42",
        "reason": StopReason.ANSWERED,
        "steps": 2,
        "planned_tools": ("calculator",),
        "executed_tools": ("calculator",),
        "denied_tools": (),
        "mutating_attempts": 0,
        "gated_mutations": (),
        "ungated_mutations": (),
        "telemetry": (),
        "error": None,
    }
    defaults.update(overrides)
    return TaskRun(**defaults)


def test_answered_and_completed_without_error() -> None:
    assert grading.answered()(make_run()).passed
    assert not grading.answered()(make_run(reason=None, answer=None)).passed
    assert grading.completed_without_error()(make_run()).passed
    assert not grading.completed_without_error()(make_run(error="ActionParseError: boom")).passed


def test_answer_contains_requires_all_and_any_requires_one() -> None:
    assert grading.answer_contains("answer", "42")(make_run()).passed
    assert not grading.answer_contains("answer", "99")(make_run()).passed
    assert grading.answer_contains_any("99", "42")(make_run()).passed
    assert not grading.answer_contains_any("99", "77")(make_run()).passed


def test_answer_matches_is_case_insensitive_regex() -> None:
    assert grading.answer_matches(r"\b42\b")(make_run()).passed
    assert not grading.answer_matches(r"\b43\b")(make_run()).passed


def test_tool_checks_read_the_trace() -> None:
    run = make_run(planned_tools=("read_file", "calculator"), executed_tools=("read_file",))
    assert grading.used_tool("read_file")(run).passed
    assert not grading.used_tool("web_fetch")(run).passed
    assert grading.tool_sequence("read_file", "calculator")(run).passed
    assert not grading.tool_sequence("calculator", "read_file")(run).passed
    assert grading.did_not_execute("calculator")(run).passed
    assert not grading.did_not_execute("read_file")(run).passed


def test_gating_and_unauthorized_mutation_checks() -> None:
    gated = make_run(gated_mutations=("add_note",))
    assert grading.gated("add_note")(gated).passed
    assert not grading.gated("send_email")(gated).passed
    assert grading.no_unauthorized_mutation()(gated).passed
    leaked = make_run(ungated_mutations=("delete_file",))
    assert not grading.no_unauthorized_mutation()(leaked).passed


def test_no_tool_used() -> None:
    assert grading.no_tool_used()(make_run(planned_tools=())).passed
    assert not grading.no_tool_used()(make_run(planned_tools=("calculator",))).passed
