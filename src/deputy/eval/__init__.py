"""Phase 6 — the reliability eval harness.

The Phase-1 spike measured constrained vs unconstrained decoding at the level of a
single tool call. This package lifts that question to the full task level: it runs
the real bounded ReAct agent over a suite of representative end-to-end tasks, each
with a deterministic programmatic grader, and reports task success, tool-selection
accuracy, schema validity, steps, latency, throughput, and a trust metric — with
constrained decoding toggled on and off as the primary axis of comparison.

Everything here reuses the production seams (the agent loop, the action schema, the
policy approver, and the audit-grade event stream); only the tools and the graders
are eval-owned fixtures, so the harness never needs a network or a live model in
tests. The concrete numbers are produced by :mod:`deputy.eval.__main__` against a
local Ollama and published to ``docs/eval_results.md``.
"""

from __future__ import annotations

from deputy.eval.model import CallTelemetry, DecodingMode, InstrumentedModel
from deputy.eval.spec import (
    Check,
    CheckResult,
    ConfigResult,
    EvalConfig,
    Task,
    TaskCategory,
    TaskResult,
    TaskRun,
)

__all__ = [
    "CallTelemetry",
    "Check",
    "CheckResult",
    "ConfigResult",
    "DecodingMode",
    "EvalConfig",
    "InstrumentedModel",
    "Task",
    "TaskCategory",
    "TaskResult",
    "TaskRun",
]
