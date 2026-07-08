"""The primary experimental lever: constrained decoding, on or off.

:class:`InstrumentedModel` wraps any :class:`~deputy.model.ChatModel` and does two
things the harness needs. First, it realizes the on/off axis: the agent always
builds an action schema, so ``FREEFORM`` simulates unconstrained decoding by
dropping that schema before the call reaches the runtime, while ``GRAMMAR`` passes
it through unchanged (Ollama's ``format`` field — the exact mechanism the spike
used). Second, it records per-call telemetry — wall-clock latency, whether the
output parses back into a typed action, and Ollama's decode counters — so the
harness can aggregate schema validity, latency, and tokens/sec without the agent
knowing it is being measured.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from deputy.actions import ActionParseError, parse_action
from deputy.model import ChatModel, ChatResponse, Message
from deputy.tools import ToolRegistry


class DecodingMode(StrEnum):
    GRAMMAR = "grammar"  # constrained: the action schema reaches the runtime
    FREEFORM = "freeform"  # unconstrained: the schema is dropped before the call

    @property
    def constrained(self) -> bool:
        return self is DecodingMode.GRAMMAR


@dataclass(frozen=True)
class CallTelemetry:
    """One model call, as the harness sees it."""

    latency_s: float
    schema_valid: bool  # output parsed back into a typed action the loop can run
    eval_count: int
    eval_duration_ns: int


class InstrumentedModel:
    """A :class:`ChatModel` that toggles decoding mode and records every call."""

    def __init__(
        self, inner: ChatModel, registry: ToolRegistry, *, mode: DecodingMode
    ) -> None:
        self._inner = inner
        self._registry = registry
        self._mode = mode
        self._calls: list[CallTelemetry] = []

    @property
    def calls(self) -> tuple[CallTelemetry, ...]:
        return tuple(self._calls)

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        effective = schema if self._mode.constrained else None
        start = time.perf_counter()
        response = self._inner.chat(
            messages,
            schema=effective,
            temperature=temperature,
            seed=seed,
            timeout=timeout,
        )
        latency_s = time.perf_counter() - start
        self._calls.append(
            CallTelemetry(
                latency_s=latency_s,
                schema_valid=self._parses(response.text) if schema is not None else True,
                eval_count=response.eval_count,
                eval_duration_ns=response.eval_duration_ns,
            )
        )
        return response

    def _parses(self, text: str) -> bool:
        # Task-level schema validity is exactly "the loop can turn this step into a
        # typed action" — the property constrained decoding guarantees and whose
        # absence is what breaks the loop, so we measure it via the loop's own parser.
        try:
            parse_action(text, self._registry)
        except ActionParseError:
            return False
        return True
