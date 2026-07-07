"""Typed client for the local model runtime (Ollama).

The agent depends only on the :class:`ChatModel` protocol, so tests inject a
scripted fake and never touch the network. :class:`OllamaClient` is the real
implementation and carries over the spike's proven lever: Ollama's ``format``
field set to a JSON Schema, which constrains decoding to schema-valid output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, Self

import httpx

DEFAULT_HOST = "http://127.0.0.1:11434"

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatResponse:
    text: str


class ChatModel(Protocol):
    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse: ...


class Embedder(Protocol):
    def embed(self, text: str, *, timeout: float | None = None) -> list[float]: ...


class OllamaClient:
    """Blocking Ollama adapter implementing both model protocols."""

    def __init__(
        self,
        model: str,
        host: str = DEFAULT_HOST,
        *,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._http = httpx.Client(base_url=host, timeout=timeout, transport=transport)

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
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": options,
        }
        if schema is not None:
            payload["format"] = schema

        body = self._post("/api/chat", payload, timeout)
        message = body.get("message") or {}
        return ChatResponse(text=str(message.get("content", "")))

    def embed(self, text: str, *, timeout: float | None = None) -> list[float]:
        body = self._post("/api/embed", {"model": self._model, "input": text}, timeout)
        vectors = body.get("embeddings") or []
        if not vectors:
            raise ValueError("Ollama returned no embeddings")
        return [float(x) for x in vectors[0]]

    def _post(self, path: str, payload: Mapping[str, Any], timeout: float | None) -> Any:
        # httpx reads timeout=None as "no timeout", so only override the client
        # default when a per-call budget is actually supplied.
        response = (
            self._http.post(path, json=payload)
            if timeout is None
            else self._http.post(path, json=payload, timeout=timeout)
        )
        response.raise_for_status()
        return response.json()
