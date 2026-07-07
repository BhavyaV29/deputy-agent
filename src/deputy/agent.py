"""The bounded ReAct loop: plan an action, act, observe, repeat until done."""

from __future__ import annotations

from dataclasses import dataclass

from deputy.actions import FinalAnswer, ToolCall, action_schema, parse_action
from deputy.approvals import ApprovalCallback, auto_approve
from deputy.critic import Critic
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    Event,
    EventSink,
    RunFinished,
    StopReason,
    ToolObserved,
)
from deputy.model import ChatModel, Message
from deputy.prompts import critic_message, denial_message, observation_message, system_prompt
from deputy.tools import ToolRegistry


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 8
    temperature: float = 0.0
    seed: int | None = None
    request_timeout: float | None = 60.0

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")


@dataclass(frozen=True)
class AgentResult:
    answer: str | None  # None when the step ceiling is hit without a final answer
    steps: int
    reason: StopReason
    events: tuple[Event, ...]


class Agent:
    def __init__(
        self,
        model: ChatModel,
        registry: ToolRegistry,
        *,
        config: AgentConfig | None = None,
        approve: ApprovalCallback = auto_approve,
        critic: Critic | None = None,
        on_event: EventSink | None = None,
    ) -> None:
        if len(registry) == 0:
            raise ValueError("registry must contain at least one tool")
        self._model = model
        self._registry = registry
        self._config = config or AgentConfig()
        self._approve = approve
        self._critic = critic
        self._on_event = on_event

    def run(self, goal: str) -> AgentResult:
        cfg = self._config
        schema = action_schema(self._registry)
        messages = [
            Message("system", system_prompt(self._registry)),
            Message("user", goal),
        ]
        events: list[Event] = []

        def emit(event: Event) -> None:
            events.append(event)
            if self._on_event is not None:
                self._on_event(event)

        for step in range(1, cfg.max_steps + 1):
            response = self._model.chat(
                messages,
                schema=schema,
                temperature=cfg.temperature,
                seed=cfg.seed,
                timeout=cfg.request_timeout,
            )
            # With constrained decoding the step is guaranteed parseable, so a
            # parse failure is a real misconfiguration and is surfaced, not looped.
            action = parse_action(response.text, self._registry)
            emit(ActionPlanned(step, action))

            if isinstance(action, FinalAnswer):
                rejection = self._verify(goal, action.text)
                if rejection is None:
                    emit(RunFinished(step, action.text, StopReason.ANSWERED))
                    return AgentResult(action.text, step, StopReason.ANSWERED, tuple(events))
                emit(AnswerRejected(step, action.text, rejection))
                messages.append(Message("assistant", response.text))
                messages.append(Message("user", critic_message(rejection)))
                continue

            messages.append(Message("assistant", response.text))
            decision = self._approve(action)
            if not decision.approved:
                emit(ActionDenied(step, action, decision.reason))
                messages.append(Message("user", denial_message(action.tool, decision.reason)))
                continue

            observation, ok = self._execute(action)
            emit(ToolObserved(step, action, observation, ok))
            messages.append(Message("user", observation_message(action.tool, observation)))

        emit(RunFinished(cfg.max_steps, None, StopReason.MAX_STEPS))
        return AgentResult(None, cfg.max_steps, StopReason.MAX_STEPS, tuple(events))

    def _verify(self, goal: str, answer: str) -> str | None:
        """Return None to accept the answer, or feedback text to reject it."""
        if self._critic is None:
            return None
        result = self._critic(goal, answer)
        if result.accepted:
            return None
        return result.feedback or "answer did not pass the self-check"

    def _execute(self, call: ToolCall) -> tuple[str, bool]:
        tool = self._registry.get(call.tool)
        try:
            return tool.handler(call.args), True
        except Exception as exc:  # a tool fault becomes an observation, never a crash
            return f"{type(exc).__name__}: {exc}", False
