"""InstrumentedModel: the decoding-mode toggle and per-call telemetry."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from deputy.actions import action_schema
from deputy.eval.environment import CALCULATOR, build_registry
from deputy.eval.model import DecodingMode, InstrumentedModel
from deputy.model import ChatResponse, Message

_CALL = json.dumps({"tool": CALCULATOR, "args": {"expression": "1 + 1"}})


class SpyModel:
    """Records the schema it was handed and replays one canned response."""

    def __init__(self, text: str, *, eval_count: int = 5, eval_duration_ns: int = 10**9) -> None:
        self._text = text
        self._eval_count = eval_count
        self._eval_duration_ns = eval_duration_ns
        self.seen_schema: Mapping[str, Any] | None | str = "unset"

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        self.seen_schema = schema
        return ChatResponse(
            self._text, eval_count=self._eval_count, eval_duration_ns=self._eval_duration_ns
        )


def _model(text: str, mode: DecodingMode) -> tuple[InstrumentedModel, SpyModel]:
    registry, _ = build_registry((CALCULATOR,))
    spy = SpyModel(text)
    return InstrumentedModel(spy, registry, mode=mode), spy


def test_grammar_forwards_the_action_schema() -> None:
    registry, _ = build_registry((CALCULATOR,))
    spy = SpyModel(_CALL)
    model = InstrumentedModel(spy, registry, mode=DecodingMode.GRAMMAR)
    schema = action_schema(registry)

    model.chat([Message("user", "go")], schema=schema)

    assert spy.seen_schema is schema


def test_freeform_drops_the_schema_before_the_runtime() -> None:
    model, spy = _model(_CALL, DecodingMode.FREEFORM)

    model.chat([Message("user", "go")], schema={"anyOf": []})

    assert spy.seen_schema is None  # the agent asked for a schema; the mode stripped it


def test_telemetry_records_latency_validity_and_counters() -> None:
    model, _ = _model(_CALL, DecodingMode.GRAMMAR)

    model.chat([Message("user", "go")], schema={"anyOf": []})

    (call,) = model.calls
    assert call.schema_valid is True
    assert call.eval_count == 5
    assert call.eval_duration_ns == 10**9
    assert call.latency_s >= 0.0


def test_unparseable_output_is_recorded_as_schema_invalid() -> None:
    model, _ = _model("this is not json", DecodingMode.FREEFORM)

    model.chat([Message("user", "go")], schema={"anyOf": []})

    assert model.calls[0].schema_valid is False


def test_validity_is_skipped_when_no_schema_is_requested() -> None:
    model, _ = _model("prose only", DecodingMode.GRAMMAR)

    model.chat([Message("user", "go")])  # no schema => not an action call

    assert model.calls[0].schema_valid is True
