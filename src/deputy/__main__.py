"""Run Deputy against a local Ollama model.

    uv run python -m deputy "what is 12 * (3 + 4)?"                 # demo tools
    uv run python -m deputy --real "what's on my calendar today?"   # real tools + RAG
    uv run python -m deputy --real --yes "save a note: buy milk"    # gated write, scripted

``--real`` assembles the built-in MCP servers and the on-device retrieval tool from
the environment; without it, the trivial demo tools are used. Risky tools are
gated: mutations, external access, and unclassified MCP tools prompt before they
run (``--yes`` answers those prompts for scripting), and every step is written to
the audit log under ``data/``.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Sequence

import httpx

from deputy.agent import AgentConfig
from deputy.app import assistant_registry, build_agent, open_audit, open_cloud
from deputy.approvals import Prompter, auto_prompter, cli_prompter
from deputy.config import DeputyConfig
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
from deputy.tools import ToolRegistry


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
    parser.add_argument("--real", action="store_true", help="use the built-in tool servers + RAG")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama chat model tag")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--max-steps", type=int, default=8, help="step ceiling")
    parser.add_argument("--critic", action="store_true", help="self-check before answering")
    parser.add_argument(
        "--yes", action="store_true", help="auto-approve gated tools (non-interactive)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = DeputyConfig.from_env()
    audit = open_audit(config)
    recorder = audit.run()
    prompter: Prompter = auto_prompter(announce=sys.stderr) if args.yes else cli_prompter()

    with contextlib.ExitStack() as stack:
        try:
            local = stack.enter_context(OllamaClient(model=args.model, host=args.host))
            cloud = open_cloud(config)
            if cloud is not None:
                stack.enter_context(cloud)
            registry = _registry(stack, args, config)
            agent = build_agent(
                config,
                registry,
                local,
                recorder=recorder,
                prompter=prompter,
                cloud=cloud,
                agent_config=AgentConfig(max_steps=args.max_steps),
                critic=model_critic(local) if args.critic else None,
                observer=lambda event: print(_describe(event), file=sys.stderr),
            )
            print(f"[audit] {audit.path} (run {recorder.run_id})", file=sys.stderr)
            result = agent.run(args.goal)
        except httpx.HTTPError as exc:
            print(f"error: could not reach Ollama at {args.host}: {exc}", file=sys.stderr)
            print("Is `ollama serve` running and the models pulled?", file=sys.stderr)
            return 1

        if result.answer is None:
            print(f"No answer within {result.steps} steps.", file=sys.stderr)
            return 1
        print(result.answer)
        return 0


def _registry(
    stack: contextlib.ExitStack, args: argparse.Namespace, config: DeputyConfig
) -> ToolRegistry:
    if not args.real:
        return demo_registry()
    embedder = stack.enter_context(OllamaClient(model=config.embeddings_model, host=args.host))
    return stack.enter_context(assistant_registry(config, embedder))


if __name__ == "__main__":
    raise SystemExit(main())
