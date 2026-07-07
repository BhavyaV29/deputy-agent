"""Local-first model routing with strictly opt-in, auditable cloud escalation.

Deputy runs on-device by default: the router only ever reaches the network when a
cloud model is *wired in* (which the config does solely on explicit opt-in) *and*
an escalation policy asks for it. Every escalation is announced to a recorder
before the request leaves the machine, so the audit trail captures exactly what
crossed the boundary. The router is a :class:`~deputy.model.ChatModel` itself, so
the agent loop uses it in place of a bare client and needs no change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

from deputy.model import ChatModel, ChatResponse, Message

EscalationPolicy = Callable[[Sequence[Message]], str | None]
"""Given the outbound transcript, return why to escalate — or None to stay local."""

Minimizer = Callable[[Sequence[Message]], Sequence[Message]]
"""Data-minimization hook: shape what actually leaves the device on escalation."""


@dataclass(frozen=True)
class RoutingDecision:
    reason: str
    provider: str
    model: str
    messages: tuple[Message, ...]  # exactly what crossed the boundary, post-minimization


RouteRecorder = Callable[[RoutingDecision], None]


def local_only(messages: Sequence[Message]) -> None:
    """The default: never escalate."""
    return None


def escalate_all(reason: str = "cloud escalation enabled") -> EscalationPolicy:
    return lambda messages: reason


def escalate_when_larger_than(chars: int) -> EscalationPolicy:
    """Escalate once a transcript outgrows the local model's comfortable budget."""

    def policy(messages: Sequence[Message]) -> str | None:
        total = sum(len(m.content) for m in messages)
        if total > chars:
            return f"transcript of {total} chars exceeds local budget of {chars}"
        return None

    return policy


class ModelRouter:
    """A :class:`ChatModel` that prefers the local model and escalates on policy."""

    def __init__(
        self,
        local: ChatModel,
        cloud: ChatModel | None = None,
        *,
        policy: EscalationPolicy = local_only,
        on_route: RouteRecorder | None = None,
        minimize: Minimizer | None = None,
        provider: str = "cloud",
        model: str = "",
    ) -> None:
        self._local = local
        self._cloud = cloud
        self._policy = policy
        self._on_route = on_route
        self._minimize = minimize
        self._provider = provider
        self._model = model

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        reason = self._should_escalate(messages)
        if reason is None or self._cloud is None:
            return self._local.chat(
                messages, schema=schema, temperature=temperature, seed=seed, timeout=timeout
            )
        outbound = tuple(self._minimize(messages) if self._minimize else messages)
        if self._on_route is not None:
            self._on_route(RoutingDecision(reason, self._provider, self._model, outbound))
        return self._cloud.chat(
            outbound, schema=schema, temperature=temperature, seed=seed, timeout=timeout
        )

    def _should_escalate(self, messages: Sequence[Message]) -> str | None:
        # Escalation is impossible unless a cloud model was explicitly wired in, so a
        # misconfigured policy can never push data off the device on its own.
        if self._cloud is None:
            return None
        return self._policy(messages)


class OpenAIClient:
    """Minimal OpenAI-compatible chat client used only for opt-in escalation."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if seed is not None:
            payload["seed"] = seed
        if schema is not None:
            # Ask for a JSON object rather than a pinned schema: strict structured
            # outputs vary by provider, and the loop validates the shape anyway.
            payload["response_format"] = {"type": "json_object"}

        body = self._post("/chat/completions", payload, timeout)
        choices = body.get("choices") or []
        if not choices:
            raise ValueError("OpenAI-compatible response had no choices")
        message = choices[0].get("message") or {}
        return ChatResponse(text=str(message.get("content", "")))

    def _post(self, path: str, payload: Mapping[str, Any], timeout: float | None) -> Any:
        response = (
            self._http.post(path, json=payload)
            if timeout is None
            else self._http.post(path, json=payload, timeout=timeout)
        )
        response.raise_for_status()
        return response.json()
