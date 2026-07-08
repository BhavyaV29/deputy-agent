"""The eval's vocabulary: what a task is, what a run produced, how it scored.

These are plain data structures shared by the suite, the grader primitives, the
runner, and the reporters, kept free of any behavior so every other eval module
can import them without a cycle. A :class:`Task` pairs a prompt with the tools it
may use and a tuple of programmatic checks; running it yields a :class:`TaskRun`
(the observable trace), which the checks score into a :class:`TaskResult`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from deputy.eval.model import CallTelemetry, DecodingMode
from deputy.events import StopReason


class TaskCategory(StrEnum):
    TOOL_SELECTION = "tool_selection"
    MULTI_STEP = "multi_step"
    RAG = "rag"
    APPROVAL_GATING = "approval_gating"
    GRACEFUL_FAILURE = "graceful_failure"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class TaskRun:
    """Everything observable about one task execution, for graders to inspect."""

    task_id: str
    prompt: str
    answer: str | None
    reason: StopReason | None  # None when the loop raised before finishing
    steps: int
    planned_tools: tuple[str, ...]  # tool calls the model chose, in order
    executed_tools: tuple[str, ...]  # tools that actually ran (approved)
    denied_tools: tuple[str, ...]  # tool calls the approval gate blocked
    mutating_attempts: int  # planned calls to a mutating tool (the trust denominator)
    gated_mutations: tuple[str, ...]  # mutating tools routed through the approval gate
    ungated_mutations: tuple[str, ...]  # mutating tools that ran without approval
    telemetry: tuple[CallTelemetry, ...]
    error: str | None

    def called(self, tool: str) -> bool:
        return tool in self.planned_tools

    def executed(self, tool: str) -> bool:
        return tool in self.executed_tools

    @property
    def answer_lower(self) -> str:
        return (self.answer or "").lower()


Check = Callable[[TaskRun], CheckResult]


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    category: TaskCategory
    tools: tuple[str, ...]  # environment tools exposed to the agent for this task
    expected_tools: frozenset[str]  # tools the agent should route to (empty = none)
    checks: tuple[Check, ...]  # all must pass for the task to count as a success
    max_steps: int = 5


@dataclass(frozen=True)
class TaskResult:
    task: Task
    run: TaskRun
    checks: tuple[CheckResult, ...]
    success: bool
    selection_correct: bool


@dataclass(frozen=True)
class EvalConfig:
    model: str
    mode: DecodingMode
    seed: int = 0
    temperature: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.model} / {self.mode.value}"


@dataclass(frozen=True)
class ConfigResult:
    config: EvalConfig
    results: tuple[TaskResult, ...]
