"""Optional verification hook run before a final answer is returned."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from deputy.model import ChatModel, Message


@dataclass(frozen=True)
class CriticResult:
    accepted: bool
    feedback: str = ""


Critic = Callable[[str, str], CriticResult]

_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["ok", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You verify assistant answers. Decide whether the draft answer fully and correctly "
    'satisfies the user\'s goal. Respond with JSON {"ok": <bool>, "reason": <text>}.'
)


def model_critic(model: ChatModel, *, temperature: float = 0.0) -> Critic:
    """A critic that asks the model to grade its own draft under constrained decoding."""

    def review(goal: str, answer: str) -> CriticResult:
        messages = [
            Message("system", _SYSTEM),
            Message("user", f"Goal:\n{goal}\n\nDraft answer:\n{answer}"),
        ]
        response = model.chat(messages, schema=_VERDICT_SCHEMA, temperature=temperature)
        try:
            verdict = json.loads(response.text)
            ok = bool(verdict["ok"])
            reason = str(verdict.get("reason", ""))
        except (json.JSONDecodeError, KeyError, TypeError):
            # A malformed self-check must not block an otherwise-usable answer.
            return CriticResult(accepted=True)
        return CriticResult(accepted=ok, feedback="" if ok else reason)

    return review
