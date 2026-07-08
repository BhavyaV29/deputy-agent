"""Rendering the console summary and the published Markdown report."""

from __future__ import annotations

from deputy.eval.metrics import aggregate
from deputy.eval.model import CallTelemetry, DecodingMode
from deputy.eval.report import render_console, render_markdown
from deputy.eval.spec import ConfigResult, EvalConfig, Task, TaskCategory, TaskResult, TaskRun
from deputy.events import StopReason


def _config_result(mode: DecodingMode, *, success: bool, schema_valid: bool) -> ConfigResult:
    run = TaskRun(
        task_id="rag_vacation",
        prompt="p",
        answer="ans" if success else None,
        reason=StopReason.ANSWERED if success else None,
        steps=2,
        planned_tools=("search_docs",),
        executed_tools=("search_docs",),
        denied_tools=(),
        mutating_attempts=0,
        gated_mutations=(),
        ungated_mutations=(),
        telemetry=(CallTelemetry(0.4, schema_valid, 12, 10**9),),
        error=None if success else "ActionParseError: bad json",
    )
    task = Task("rag_vacation", "p", TaskCategory.RAG, ("search_docs",), frozenset(), ())
    result = TaskResult(task, run, (), success, selection_correct=True)
    return ConfigResult(EvalConfig("qwen2.5:3b", mode), (result,))


def test_render_markdown_has_table_categories_and_interpretation() -> None:
    grammar = _config_result(DecodingMode.GRAMMAR, success=True, schema_valid=True)
    freeform = _config_result(DecodingMode.FREEFORM, success=False, schema_valid=False)
    results = [grammar, freeform]
    metrics = [aggregate(r) for r in results]

    doc = render_markdown(metrics, results, task_count=1, seed=0, temperature=0.0)

    assert "# Eval: task-level reliability under constrained decoding" in doc
    assert "`qwen2.5:3b`" in doc
    assert "grammar" in doc and "freeform" in doc
    assert "| Trust |" in doc
    assert TaskCategory.RAG.value in doc
    assert "## Interpretation" in doc
    assert "Constrained decoding held schema validity" in doc


def test_render_console_emits_a_row_per_config() -> None:
    grammar = _config_result(DecodingMode.GRAMMAR, success=True, schema_valid=True)
    freeform = _config_result(DecodingMode.FREEFORM, success=False, schema_valid=False)
    metrics = [aggregate(grammar), aggregate(freeform)]

    table = render_console(metrics)

    assert "Schema-valid" in table
    assert table.count("qwen2.5:3b") == 2
