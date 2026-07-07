"""Run the constrained-vs-unconstrained tool-call reliability spike.

uv run python -m deputy.spike
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from deputy.spike.client import DEFAULT_HOST, OllamaClient
from deputy.spike.report import render_console, render_markdown
from deputy.spike.runner import Attempt, Condition, run_spike, summarize
from deputy.spike.tools import system_prompt


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deputy.spike", description=__doc__)
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama model tag")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--repetitions", type=int, default=3, help="runs per prompt per condition")
    parser.add_argument("--temperature", type=float, default=1.0, help="sampling temperature")
    parser.add_argument("--out", default="docs/spike_results.md", help="Markdown report path")
    return parser.parse_args(argv)


def _progress(attempt: Attempt) -> None:
    schema = "valid" if attempt.schema_valid else "INVALID"
    pick = "hit" if attempt.selection_correct else "miss"
    print(
        f"  {attempt.condition.value:<13} {attempt.prompt.expected_tool:<13} "
        f"schema={schema:<7} tool={pick}",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    model: str = args.model
    host: str = args.host
    repetitions: int = args.repetitions
    temperature: float = args.temperature

    print(f"Running spike against {model} at {host}...", file=sys.stderr)
    try:
        with OllamaClient(model=model, host=host) as client:
            # Load the model once up front so the one-time weight load does not
            # skew the per-call latency of whichever condition happens to run first.
            client.generate(system_prompt(), "warm up", temperature=0.0)
            attempts = run_spike(
                client,
                repetitions=repetitions,
                temperature=temperature,
                on_attempt=_progress,
            )
    except httpx.HTTPError as exc:
        print(f"error: could not talk to Ollama at {host}: {exc}", file=sys.stderr)
        print("Is `ollama serve` running and the model pulled?", file=sys.stderr)
        return 1

    summaries = [summarize(attempts, condition) for condition in Condition]
    print(render_console(model, summaries))

    report = render_markdown(
        model,
        summaries,
        prompt_count=len({attempt.prompt.text for attempt in attempts}),
        repetitions=repetitions,
        temperature=temperature,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"\nWrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
