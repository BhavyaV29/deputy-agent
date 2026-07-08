"""Metric aggregation over scored task results."""

from __future__ import annotations

from deputy.eval.metrics import aggregate, success_by_category
from deputy.eval.model import CallTelemetry, DecodingMode
from deputy.eval.spec import ConfigResult, EvalConfig, Task, TaskCategory, TaskResult, TaskRun
from deputy.events import StopReason


def _task(category: TaskCategory = TaskCategory.TOOL_SELECTION) -> Task:
    return Task("t", "p", category, ("calculator",), frozenset(), ())


def _telemetry(
    n: int, *, valid: bool, eval_count: int, eval_duration_ns: int, latency_s: float
) -> tuple[CallTelemetry, ...]:
    return tuple(CallTelemetry(latency_s, valid, eval_count, eval_duration_ns) for _ in range(n))


def _result(
    *,
    success: bool,
    selection: bool,
    reason: StopReason | None,
    steps: int,
    telemetry: tuple[CallTelemetry, ...],
    category: TaskCategory = TaskCategory.TOOL_SELECTION,
    mutating_attempts: int = 0,
    ungated: tuple[str, ...] = (),
    error: str | None = None,
) -> TaskResult:
    run = TaskRun(
        task_id="t",
        prompt="p",
        answer=None if error else "ans",
        reason=reason,
        steps=steps,
        planned_tools=(),
        executed_tools=(),
        denied_tools=(),
        mutating_attempts=mutating_attempts,
        gated_mutations=(),
        ungated_mutations=ungated,
        telemetry=telemetry,
        error=error,
    )
    return TaskResult(_task(category), run, (), success, selection)


def _config_result(*results: TaskResult) -> ConfigResult:
    return ConfigResult(EvalConfig("fake-model", DecodingMode.GRAMMAR), tuple(results))


def test_aggregate_reduces_every_headline_metric() -> None:
    ok = _result(
        success=True,
        selection=True,
        reason=StopReason.ANSWERED,
        steps=2,
        telemetry=_telemetry(2, valid=True, eval_count=10, eval_duration_ns=10**9, latency_s=0.5),
    )
    crashed = _result(
        success=False,
        selection=False,
        reason=None,
        steps=1,
        telemetry=_telemetry(1, valid=False, eval_count=0, eval_duration_ns=0, latency_s=0.2),
        error="ActionParseError: boom",
    )

    metrics = aggregate(_config_result(ok, crashed))

    assert metrics.tasks == 2
    assert metrics.success_rate == 0.5
    assert metrics.tool_selection_accuracy == 0.5
    assert metrics.schema_valid_rate == 2 / 3
    assert metrics.avg_steps == 2.0  # only the ANSWERED task counts toward completion
    assert metrics.avg_latency_s == (0.5 + 0.5 + 0.2) / 3
    assert metrics.tokens_per_second == 10.0  # 20 tokens over 2.0s of eval time
    assert metrics.crashes == 1
    assert metrics.trust_metric == 1.0  # no mutations attempted


def test_trust_metric_drops_when_a_mutation_slips_the_gate() -> None:
    leaked = _result(
        success=False,
        selection=True,
        reason=StopReason.ANSWERED,
        steps=1,
        telemetry=_telemetry(1, valid=True, eval_count=1, eval_duration_ns=10**9, latency_s=0.1),
        mutating_attempts=2,
        ungated=("delete_file",),
    )

    metrics = aggregate(_config_result(leaked))

    assert metrics.mutation_attempts == 2
    assert metrics.ungated_mutations == 1
    assert metrics.trust_metric == 0.5


def test_success_by_category_groups_results() -> None:
    a = _result(
        success=True,
        selection=True,
        reason=StopReason.ANSWERED,
        steps=1,
        telemetry=(),
        category=TaskCategory.RAG,
    )
    b = _result(
        success=False,
        selection=True,
        reason=StopReason.ANSWERED,
        steps=1,
        telemetry=(),
        category=TaskCategory.RAG,
    )
    c = _result(
        success=True,
        selection=True,
        reason=StopReason.ANSWERED,
        steps=1,
        telemetry=(),
        category=TaskCategory.REFUSAL,
    )

    scores = success_by_category(_config_result(a, b, c))

    assert scores[TaskCategory.RAG] == 0.5
    assert scores[TaskCategory.REFUSAL] == 1.0
