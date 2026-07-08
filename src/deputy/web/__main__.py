"""Launch the Deputy web UI on loopback.

    uv run python -m deputy.web                 # http://127.0.0.1:8000
    uv run python -m deputy.web --port 8080 --critic

The server binds 127.0.0.1 only: Deputy is a private, local-first agent, so the
UI is never reachable off-host. Model and tool settings mirror the CLI and are
read from the environment (see DeputyConfig).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from deputy.config import DeputyConfig
from deputy.model import DEFAULT_HOST
from deputy.web.server import create_app
from deputy.web.service import live_service

_BIND_HOST = "127.0.0.1"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deputy-web", description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="loopback port to serve on")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama chat model tag")
    parser.add_argument("--ollama-host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--max-steps", type=int, default=8, help="agent step ceiling")
    parser.add_argument("--critic", action="store_true", help="self-check before answering")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    import uvicorn

    args = _parse_args(argv)
    config = DeputyConfig.from_env()
    with live_service(
        config,
        model=args.model,
        host=args.ollama_host,
        max_steps=args.max_steps,
        use_critic=args.critic,
    ) as service:
        app = create_app(service)
        print(f"Deputy web UI on http://{_BIND_HOST}:{args.port} (audit: {service.audit.path})")
        uvicorn.run(app, host=_BIND_HOST, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
