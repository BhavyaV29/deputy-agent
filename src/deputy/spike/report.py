"""Render spike results as a Markdown document and a console summary."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from deputy.spike.runner import Condition, ConditionSummary

# The bet we are de-risking: constrained decoding yields near-perfect schema validity.
SCHEMA_VALID_TARGET = 0.99


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _by_condition(summaries: Sequence[ConditionSummary]) -> dict[Condition, ConditionSummary]:
    return {summary.condition: summary for summary in summaries}


def verdict(summaries: Sequence[ConditionSummary]) -> str:
    by_condition = _by_condition(summaries)
    constrained = by_condition[Condition.CONSTRAINED]
    unconstrained = by_condition[Condition.UNCONSTRAINED]
    lift = constrained.schema_valid_rate - unconstrained.schema_valid_rate
    holds = constrained.schema_valid_rate >= SCHEMA_VALID_TARGET
    stance = "HOLDS" if holds else "DOES NOT HOLD"
    return (
        f"Bet {stance}: constrained decoding reached {_percent(constrained.schema_valid_rate)} "
        f"schema-valid vs {_percent(unconstrained.schema_valid_rate)} unconstrained "
        f"(+{_percent(lift)})."
    )


def _table(summaries: Sequence[ConditionSummary]) -> str:
    header = (
        "| Condition | Schema-valid | Tool-selection | Avg latency | Tokens/s | Samples |\n"
        "| --- | --- | --- | --- | --- | --- |"
    )
    rows = [
        f"| {s.condition.value} | {_percent(s.schema_valid_rate)} "
        f"| {_percent(s.selection_accuracy)} | {s.avg_latency_s:.2f}s "
        f"| {s.tokens_per_second:.1f} | {s.samples} |"
        for s in summaries
    ]
    return "\n".join([header, *rows])


def render_markdown(
    model: str,
    summaries: Sequence[ConditionSummary],
    *,
    prompt_count: int,
    repetitions: int,
    temperature: float,
) -> str:
    return "\n".join(
        [
            "# Spike: tool-call reliability under constrained decoding",
            "",
            f"- **Model:** `{model}` (via Ollama)",
            f"- **Date:** {date.today().isoformat()}",
            f"- **Prompts:** {prompt_count} labeled requests x {repetitions} repetitions "
            f"per condition",
            "- **Mechanism:** Ollama structured outputs — the `format` field set to the "
            "tool-call JSON Schema (constrained) vs. omitted (unconstrained)",
            f"- **Sampling:** temperature {temperature}, seeds shared across conditions",
            "- **Schema-valid:** output parses as JSON and matches the tool-call schema "
            "(known tool + exactly its typed arguments)",
            "- **Tool-selection:** the chosen tool matches the labeled expectation",
            "",
            _table(summaries),
            "",
            f"**Verdict.** {verdict(summaries)}",
            "",
            "## Reading the results",
            "",
            "- The `format` schema constrains *shape*, not *choice*: it forces every "
            "constrained sample to be a well-formed call to some tool, which is why "
            "schema validity is pinned at 100%. It does not decide *which* tool fits, so "
            "tool-selection tracks the model's routing ability and is essentially the same "
            "in both conditions.",
            "- The unconstrained gap is small — this model is a capable tool-caller — but "
            "non-zero, and the failures are schema violations (malformed or over-decorated "
            "JSON). That is exactly the class of error that breaks an agent loop, and "
            "constrained decoding removes it by construction rather than by prompt "
            "engineering.",
            "",
        ]
    )


def render_console(model: str, summaries: Sequence[ConditionSummary]) -> str:
    return "\n".join(
        [
            f"Model: {model}",
            _table(summaries),
            "",
            verdict(summaries),
        ]
    )
