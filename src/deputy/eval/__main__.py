"""Run the reliability eval matrix against a local Ollama and publish the report.

    uv run python -m deputy.eval
    uv run python -m deputy.eval --model qwen2.5:3b --model llama3.2:3b
    uv run python -m deputy.eval --limit 6 --out docs/eval_results.md

For every requested model the harness runs the whole task suite twice — constrained
(`grammar`) and unconstrained (`freeform`) decoding — prints the matrix, and writes
a Markdown report. Models that are not served locally are skipped with a warning.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from deputy.eval.harness import run_config
from deputy.eval.metrics import aggregate
from deputy.eval.model import DecodingMode
from deputy.eval.report import render_console, render_markdown
from deputy.eval.spec import ConfigResult, EvalConfig, TaskResult
from deputy.eval.suite import TASK_SUITE
from deputy.model import DEFAULT_HOST, Message, OllamaClient

DEFAULT_MODELS = ("qwen2.5:3b",)
MODES = (DecodingMode.GRAMMAR, DecodingMode.FREEFORM)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deputy.eval", description=__doc__)
    parser.add_argument(
        "--model", action="append", dest="models", help="Ollama chat model tag (repeatable)"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--seed", type=int, default=0, help="sampling seed, fixed across configs")
    parser.add_argument("--temperature", type=float, default=0.0, help="sampling temperature")
    parser.add_argument("--limit", type=int, default=None, help="run only the first N tasks")
    parser.add_argument("--out", default="docs/eval_results.md", help="Markdown report path")
    return parser.parse_args(argv)


def _served_models(host: str) -> set[str]:
    response = httpx.get(f"{host}/api/tags", timeout=5.0)
    response.raise_for_status()
    return {str(m.get("name", "")) for m in response.json().get("models", [])}


def _is_served(served: set[str], model: str) -> bool:
    return any(name == model or name.startswith(f"{model}:") for name in served)


def _progress(result: TaskResult) -> None:
    mark = "PASS" if result.success else "FAIL"
    print(f"    [{mark}] {result.task.id:<22} steps={result.run.steps}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    models = tuple(args.models) if args.models else DEFAULT_MODELS
    tasks = TASK_SUITE[: args.limit] if args.limit else TASK_SUITE

    try:
        served = _served_models(args.host)
    except httpx.HTTPError as exc:
        print(f"error: could not reach Ollama at {args.host}: {exc}", file=sys.stderr)
        print("Is `ollama serve` running?", file=sys.stderr)
        return 1

    results: list[ConfigResult] = []
    for model in models:
        if not _is_served(served, model):
            print(f"warning: {model!r} is not served at {args.host}; skipping", file=sys.stderr)
            continue
        try:
            with OllamaClient(model=model, host=args.host) as client:
                client.chat([Message("user", "ready?")], temperature=0.0)  # load weights once
                for mode in MODES:
                    config = EvalConfig(
                        model=model, mode=mode, seed=args.seed, temperature=args.temperature
                    )
                    print(f"running {config.label} over {len(tasks)} tasks...", file=sys.stderr)
                    results.append(run_config(client, config, tasks, on_result=_progress))
        except httpx.HTTPError as exc:
            print(f"error: Ollama call failed for {model!r}: {exc}", file=sys.stderr)
            return 1

    if not results:
        print("error: no requested models were available", file=sys.stderr)
        return 1

    metrics = [aggregate(result) for result in results]
    print("\n" + render_console(metrics))

    report = render_markdown(
        metrics, results, task_count=len(tasks), seed=args.seed, temperature=args.temperature
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"\nwrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
