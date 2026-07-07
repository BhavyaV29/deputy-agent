"""A thin httpx wrapper over Ollama's chat endpoint.

Kept deliberately small: one blocking call that optionally carries a ``format``
schema (Ollama's structured-outputs / constrained-decoding knob) and surfaces
the timing counters the spike reports on.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

DEFAULT_HOST = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class Generation:
    text: str
    latency_s: float
    eval_count: int
    eval_duration_ns: int

    @property
    def tokens_per_second(self) -> float:
        if self.eval_duration_ns <= 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)


class OllamaClient:
    def __init__(self, model: str, host: str = DEFAULT_HOST, timeout: float = 120.0) -> None:
        self._model = model
        self._http = httpx.Client(base_url=host, timeout=timeout)

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

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> Generation:
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": options,
        }
        if schema is not None:
            payload["format"] = schema

        start = time.perf_counter()
        response = self._http.post("/api/chat", json=payload)
        latency_s = time.perf_counter() - start
        response.raise_for_status()

        body = response.json()
        message = body.get("message") or {}
        return Generation(
            text=message.get("content", ""),
            latency_s=latency_s,
            eval_count=int(body.get("eval_count", 0)),
            eval_duration_ns=int(body.get("eval_duration", 0)),
        )
