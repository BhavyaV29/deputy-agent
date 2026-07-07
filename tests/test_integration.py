"""End-to-end loop against a real Ollama model.

Skipped unless a local Ollama is serving ``qwen2.5:3b``; the rest of the suite
never needs a model.
"""

from __future__ import annotations

import httpx
import pytest

from deputy.agent import Agent, AgentConfig
from deputy.demo import demo_registry
from deputy.model import DEFAULT_HOST, OllamaClient

MODEL = "qwen2.5:3b"


def _model_available() -> bool:
    try:
        response = httpx.get(f"{DEFAULT_HOST}/api/tags", timeout=2.0)
        response.raise_for_status()
        models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return False
    return any(str(m.get("name", "")).startswith(MODEL) for m in models)


pytestmark = pytest.mark.skipif(not _model_available(), reason=f"{MODEL} not served locally")


def test_agent_reaches_a_final_answer_using_the_calculator() -> None:
    with OllamaClient(MODEL) as client:
        agent = Agent(client, demo_registry(), config=AgentConfig(max_steps=5))
        result = agent.run("Use the calculator to compute 21 * 2, then tell me the number.")

    assert result.answer is not None
    assert "42" in result.answer
