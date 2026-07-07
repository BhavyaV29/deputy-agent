"""Run the demo agent against a local Ollama model.

uv run python -m deputy "what is 12 * (3 + 4)?"
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import httpx

from deputy.agent import Agent, AgentConfig
from deputy.critic import model_critic
from deputy.demo import demo_registry
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    Event,
    RunFinished,
    ToolObserved,
)
from deputy.model import DEFAULT_HOST, OllamaClient


def _describe(event: Event) -> str:
    match event:
        case ActionPlanned(step, action):
            return f"[{step}] plan: {action}"
        case ToolObserved(step, call, observation, ok):
            status = "ok" if ok else "error"
            return f"[{step}] {call.tool} -> ({status}) {observation}"
        case ActionDenied(step, call, reason):
            return f"[{step}] denied {call.tool}: {reason}"
        case AnswerRejected(step, _, feedback):
            return f"[{step}] self-check rejected: {feedback}"
        case RunFinished(step, answer, reason):
            return f"[{step}] finished ({reason}): {answer}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deputy", description=__doc__)
    parser.add_argument("goal", help="what you want Deputy to do")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama model tag")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--max-steps", type=int, default=8, help="step ceiling")
    parser.add_argument("--critic", action="store_true", help="self-check before answering")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with OllamaClient(model=args.model, host=args.host) as client:
            agent = Agent(
                client,
                demo_registry(),
                config=AgentConfig(max_steps=args.max_steps),
                critic=model_critic(client) if args.critic else None,
                on_event=lambda event: print(_describe(event), file=sys.stderr),
            )
            result = agent.run(args.goal)
    except httpx.HTTPError as exc:
        print(f"error: could not reach Ollama at {args.host}: {exc}", file=sys.stderr)
        print("Is `ollama serve` running and the model pulled?", file=sys.stderr)
        return 1

    if result.answer is None:
        print(f"No answer within {result.steps} steps.", file=sys.stderr)
        return 1
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
