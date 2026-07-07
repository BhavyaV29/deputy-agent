"""Structured events for the audit and approval seams.

The loop emits one event per meaningful transition. A sink can persist these as
an audit trail (Phase 4) without the loop knowing anything about storage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from deputy.actions import Action, ToolCall


class StopReason(StrEnum):
    ANSWERED = "answered"
    MAX_STEPS = "max_steps"


@dataclass(frozen=True)
class ActionPlanned:
    step: int
    action: Action


@dataclass(frozen=True)
class ToolObserved:
    step: int
    call: ToolCall
    observation: str
    ok: bool  # False when the handler raised


@dataclass(frozen=True)
class ActionDenied:
    step: int
    call: ToolCall
    reason: str


@dataclass(frozen=True)
class AnswerRejected:
    step: int
    answer: str
    feedback: str


@dataclass(frozen=True)
class RunFinished:
    step: int
    answer: str | None
    reason: StopReason


Event = ActionPlanned | ToolObserved | ActionDenied | AnswerRejected | RunFinished
EventSink = Callable[[Event], None]


def fanout(*sinks: EventSink) -> EventSink:
    """Broadcast every event to each sink, in order — e.g. audit + console + UI."""

    def emit(event: Event) -> None:
        for sink in sinks:
            sink(event)

    return emit
