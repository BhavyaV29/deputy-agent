"""Drive both decoding conditions over the prompt set and aggregate the results."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from deputy.spike.client import Generation, OllamaClient
from deputy.spike.prompts import PROMPTS, Prompt
from deputy.spike.tools import system_prompt, tool_call_schema
from deputy.spike.validation import check_tool_call


class Condition(StrEnum):
    UNCONSTRAINED = "unconstrained"
    CONSTRAINED = "constrained"


@dataclass(frozen=True)
class Attempt:
    prompt: Prompt
    condition: Condition
    seed: int
    schema_valid: bool
    selection_correct: bool
    generation: Generation


@dataclass(frozen=True)
class ConditionSummary:
    condition: Condition
    samples: int
    schema_valid_rate: float
    selection_accuracy: float
    avg_latency_s: float
    tokens_per_second: float


def run_attempt(
    client: OllamaClient,
    prompt: Prompt,
    condition: Condition,
    *,
    temperature: float,
    seed: int,
) -> Attempt:
    schema = tool_call_schema() if condition is Condition.CONSTRAINED else None
    generation = client.generate(
        system_prompt(),
        prompt.text,
        schema=schema,
        temperature=temperature,
        seed=seed,
    )
    check = check_tool_call(generation.text)
    return Attempt(
        prompt=prompt,
        condition=condition,
        seed=seed,
        schema_valid=check.schema_valid,
        selection_correct=check.tool == prompt.expected_tool,
        generation=generation,
    )


def run_spike(
    client: OllamaClient,
    prompts: Sequence[Prompt] = PROMPTS,
    *,
    repetitions: int = 3,
    temperature: float = 1.0,
    on_attempt: Callable[[Attempt], None] | None = None,
) -> list[Attempt]:
    # Seeds are shared across conditions so unconstrained and constrained runs
    # see the same sampling randomness for a given prompt/repetition.
    attempts: list[Attempt] = []
    for prompt in prompts:
        for seed in range(repetitions):
            for condition in Condition:
                attempt = run_attempt(client, prompt, condition, temperature=temperature, seed=seed)
                if on_attempt is not None:
                    on_attempt(attempt)
                attempts.append(attempt)
    return attempts


def summarize(attempts: Sequence[Attempt], condition: Condition) -> ConditionSummary:
    subset = [a for a in attempts if a.condition is condition]
    if not subset:
        raise ValueError(f"no attempts recorded for {condition.value}")

    tokens = sum(a.generation.eval_count for a in subset)
    eval_seconds = sum(a.generation.eval_duration_ns for a in subset) / 1e9
    return ConditionSummary(
        condition=condition,
        samples=len(subset),
        schema_valid_rate=_rate(a.schema_valid for a in subset),
        selection_accuracy=_rate(a.selection_correct for a in subset),
        avg_latency_s=sum(a.generation.latency_s for a in subset) / len(subset),
        tokens_per_second=tokens / eval_seconds if eval_seconds > 0 else 0.0,
    )


def _rate(flags: Iterable[bool]) -> float:
    values = list(flags)
    return sum(values) / len(values) if values else 0.0
