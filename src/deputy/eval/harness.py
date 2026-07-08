"""Run a task, a config, or the whole matrix, and score what came back.

The runner assembles the *real* agent for every task — the same bounded ReAct loop
behind the same policy approver and action schema that :func:`deputy.app.build_agent`
wires for the CLI and web UI — so the eval measures the shipping system, not a
stand-in. The only substitutions are deliberate: the model is wrapped so decoding
mode can be toggled and timed, tools come from the in-process environment, and the
approval prompter is an unattended :class:`ApprovalProbe` that withholds approval
by default (nothing writes without a human) while recording that the gate engaged.
A task that raises out of the loop — the failure mode constrained decoding exists
to prevent — is caught and scored as a failure rather than aborting the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from deputy.actions import ToolCall
from deputy.agent import Agent, AgentConfig
from deputy.approvals import ApprovalDecision, ApprovalRequest, policy_approver
from deputy.eval.environment import build_registry
from deputy.eval.model import CallTelemetry, InstrumentedModel
from deputy.eval.spec import ConfigResult, EvalConfig, Task, TaskResult, TaskRun
from deputy.eval.suite import TASK_SUITE
from deputy.events import ActionDenied, ActionPlanned, Event, StopReason, ToolObserved
from deputy.model import ChatModel
from deputy.tools import ToolRegistry


class ApprovalProbe:
    """An unattended prompter: record every request, withhold approval by default."""

    def __init__(self, *, approve: bool = False) -> None:
        self._approve = approve
        self.requests: list[ApprovalRequest] = []

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        reason = "eval: approved" if self._approve else "eval: withheld pending human sign-off"
        return ApprovalDecision(self._approve, reason)


def run_task(inner_model: ChatModel, task: Task, config: EvalConfig) -> TaskResult:
    registry, _sandbox = build_registry(task.tools)
    model = InstrumentedModel(inner_model, registry, mode=config.mode)
    probe = ApprovalProbe(approve=False)
    events: list[Event] = []
    agent = Agent(
        model,
        registry,
        config=AgentConfig(
            max_steps=task.max_steps, temperature=config.temperature, seed=config.seed
        ),
        approve=policy_approver(registry, probe),
        on_event=events.append,
    )

    answer: str | None = None
    reason = None
    steps = 0
    error: str | None = None
    try:
        result = agent.run(task.prompt)
        answer, reason, steps = result.answer, result.reason, result.steps
    except Exception as exc:  # a loop that raises is itself a task failure, not a crash
        error = f"{type(exc).__name__}: {exc}"
        steps = sum(isinstance(e, ActionPlanned) for e in events)

    run = _trace(task, events, registry, probe, model.calls, answer, reason, steps, error)
    checks = tuple(grade(run) for grade in task.checks)
    success = error is None and all(c.passed for c in checks)
    return TaskResult(task, run, checks, success, _selection_correct(task, run))


def run_config(
    inner_model: ChatModel,
    config: EvalConfig,
    tasks: Sequence[Task] = TASK_SUITE,
    *,
    on_result: Callable[[TaskResult], None] | None = None,
) -> ConfigResult:
    results: list[TaskResult] = []
    for task in tasks:
        result = run_task(inner_model, task, config)
        if on_result is not None:
            on_result(result)
        results.append(result)
    return ConfigResult(config, tuple(results))


def _trace(
    task: Task,
    events: Sequence[Event],
    registry: ToolRegistry,
    probe: ApprovalProbe,
    telemetry: tuple[CallTelemetry, ...],
    answer: str | None,
    reason: StopReason | None,
    steps: int,
    error: str | None,
) -> TaskRun:
    planned: list[str] = []
    executed: list[str] = []
    denied: list[str] = []
    for event in events:
        if isinstance(event, ActionPlanned) and isinstance(event.action, ToolCall):
            planned.append(event.action.tool)
        elif isinstance(event, ToolObserved):
            executed.append(event.call.tool)
        elif isinstance(event, ActionDenied):
            denied.append(event.call.tool)

    gated_names = {req.call.tool for req in probe.requests}
    gated_mutations = tuple(
        dict.fromkeys(name for name in gated_names if _mutating(registry, name))
    )
    ungated = tuple(
        dict.fromkeys(
            name for name in executed if _mutating(registry, name) and name not in gated_names
        )
    )
    return TaskRun(
        task_id=task.id,
        prompt=task.prompt,
        answer=answer,
        reason=reason,
        steps=steps,
        planned_tools=tuple(planned),
        executed_tools=tuple(executed),
        denied_tools=tuple(denied),
        mutating_attempts=sum(_mutating(registry, name) for name in planned),
        gated_mutations=gated_mutations,
        ungated_mutations=ungated,
        telemetry=telemetry,
        error=error,
    )


def _selection_correct(task: Task, run: TaskRun) -> bool:
    if task.expected_tools:
        return task.expected_tools.issubset(set(run.planned_tools))
    return len(run.planned_tools) == 0


def _mutating(registry: ToolRegistry, name: str) -> bool:
    try:
        return registry.get(name).mutating
    except KeyError:
        return False
