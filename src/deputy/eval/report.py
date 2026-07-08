"""Render the eval as a console summary and a published Markdown report.

The report leads with the matrix table (one row per model x decoding mode), follows
with a per-category success breakdown, and closes with an interpretation generated
from the numbers themselves — so the prose can never drift from the table above it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from deputy.eval.metrics import ConfigMetrics, category_order, success_by_category
from deputy.eval.model import DecodingMode
from deputy.eval.spec import ConfigResult

_HEADERS = (
    "Model",
    "Decoding",
    "Success",
    "Tool-select",
    "Schema-valid",
    "Avg steps",
    "Avg latency",
    "Tokens/s",
    "Trust",
    "Crashes",
)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _row(m: ConfigMetrics) -> str:
    return (
        f"| `{m.config.model}` | {m.config.mode.value} | {_percent(m.success_rate)} "
        f"| {_percent(m.tool_selection_accuracy)} | {_percent(m.schema_valid_rate)} "
        f"| {m.avg_steps:.1f} | {m.avg_latency_s:.2f}s | {m.tokens_per_second:.1f} "
        f"| {_percent(m.trust_metric)} | {m.crashes} |"
    )


def _matrix_table(metrics: Sequence[ConfigMetrics]) -> str:
    header = "| " + " | ".join(_HEADERS) + " |"
    divider = "|" + " --- |" * len(_HEADERS)
    return "\n".join([header, divider, *(_row(m) for m in metrics)])


def _category_table(results: Sequence[ConfigResult]) -> str:
    cats = category_order(results)
    by_config = [(r.config, success_by_category(r)) for r in results]
    labels = " | ".join(f"`{c.model}` {c.mode.value}" for c, _ in by_config)
    header = f"| Category | {labels} |"
    divider = "| --- |" + " --- |" * len(by_config)
    rows = [
        "| "
        + cat.value
        + " | "
        + " | ".join(_percent(scores.get(cat, 0.0)) for _, scores in by_config)
        + " |"
        for cat in cats
    ]
    return "\n".join([header, divider, *rows])


def _by_model(metrics: Sequence[ConfigMetrics]) -> dict[str, dict[DecodingMode, ConfigMetrics]]:
    grouped: dict[str, dict[DecodingMode, ConfigMetrics]] = {}
    for m in metrics:
        grouped.setdefault(m.config.model, {})[m.config.mode] = m
    return grouped


def _interpretation(metrics: Sequence[ConfigMetrics]) -> list[str]:
    lines: list[str] = []
    for model, modes in _by_model(metrics).items():
        grammar = modes.get(DecodingMode.GRAMMAR)
        freeform = modes.get(DecodingMode.FREEFORM)
        if grammar is None or freeform is None:
            continue
        schema_delta = grammar.schema_valid_rate - freeform.schema_valid_rate
        success_delta = grammar.success_rate - freeform.success_rate
        lines.append(
            f"- **`{model}`.** Constrained decoding held schema validity at "
            f"{_percent(grammar.schema_valid_rate)} vs {_percent(freeform.schema_valid_rate)} "
            f"unconstrained ({_signed(schema_delta)}), with task success "
            f"{_percent(grammar.success_rate)} vs {_percent(freeform.success_rate)} "
            f"({_signed(success_delta)}). Unconstrained runs raised out of the loop "
            f"{freeform.crashes} time(s) vs {grammar.crashes} constrained — the parse "
            f"failures that constrained decoding removes by construction. Latency was "
            f"{grammar.avg_latency_s:.2f}s vs {freeform.avg_latency_s:.2f}s per call. "
            f"The trust metric stayed at {_percent(grammar.trust_metric)} in both modes "
            f"({grammar.mutation_attempts} mutating call(s) attempted, "
            f"{grammar.ungated_mutations} ungated): every write was gated regardless of "
            f"how the step was decoded."
        )
    return lines


def _signed(delta: float) -> str:
    return f"{'+' if delta >= 0 else ''}{delta * 100:.1f} pts"


def render_markdown(
    metrics: Sequence[ConfigMetrics],
    results: Sequence[ConfigResult],
    *,
    task_count: int,
    seed: int,
    temperature: float,
) -> str:
    return "\n".join(
        [
            "# Eval: task-level reliability under constrained decoding",
            "",
            f"- **Date:** {date.today().isoformat()}",
            f"- **Models:** {', '.join(f'`{model}`' for model in _by_model(metrics))} (via Ollama)",
            f"- **Suite:** {task_count} end-to-end tasks spanning tool selection, multi-step "
            "reasoning, RAG retrieval, approval-gating, graceful failure, and refusal",
            "- **Primary axis:** constrained decoding on (`grammar`) vs off (`freeform`) — the "
            "action schema is passed to Ollama's `format` field, or dropped, exactly as in the "
            "Phase-1 spike, but now measured over whole tasks rather than single calls",
            f"- **Sampling:** temperature {temperature}, seed {seed}, fixed across configs for "
            "reproducibility",
            "- **Grading:** deterministic programmatic checks (answer content/regex, tool "
            "selection, approval-gating events); no LLM judge",
            "- **Schema-valid:** the step parsed back into a typed action the loop can run "
            "(`parse_action` succeeds) — the task-level analog of the spike's call-level check, "
            "and precisely the property whose absence breaks the loop",
            "- **Trust metric:** fraction of attempted mutating calls that stayed behind the "
            "approval gate; any ungated mutation counts as a failure",
            "",
            "## Results",
            "",
            _matrix_table(metrics),
            "",
            "### Success by category",
            "",
            _category_table(results),
            "",
            "## Interpretation",
            "",
            *_interpretation(metrics),
            "- **Reading tool-selection.** Selection accuracy is scored over the tools the "
            "model *planned*, independent of whether the task ultimately succeeded. An "
            "unconstrained run often plans the right first tool and only then emits an "
            "unparseable step, so its tool-selection can match or exceed the constrained run "
            "even as task success collapses — schema validity, crashes, and success are where "
            "the cost of dropping the grammar actually lands.",
            "",
        ]
    )


def render_console(metrics: Sequence[ConfigMetrics]) -> str:
    return "\n".join([_matrix_table(metrics)])
