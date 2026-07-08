"""Launch-once, use-continuously entry point for Deputy's local web UI.

    deputy-app                     # start the server, open it, keep running
    deputy-app --window            # open a native desktop window (needs the 'app' extra)
    deputy-app --no-browser        # start the server without opening anything
    python -m deputy.web.launcher  # same thing, module form

This wraps the same FastAPI app as :mod:`deputy.web` (nothing about the UI or the
agent changes) with the conveniences that make it feel like an app instead of a
command you re-run:

* **Auto-open.** Once the loopback server is up it opens your browser (or a native
  window with ``--window``) at the right URL.
* **Re-launch is safe.** If Deputy is *already* running on the preferred port it
  just opens that instance instead of failing; if some *other* process holds the
  port it picks the next free one and serves there.
* **Stays running.** It blocks until you close the window or press Ctrl+C.

The server still binds ``127.0.0.1`` only — Deputy is local-first, so the UI is
never reachable off-host. ``python -m deputy.web`` remains the plain server for
scripting and service managers.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING

import httpx

from deputy.config import DeputyConfig
from deputy.model import DEFAULT_HOST
from deputy.web.server import create_app
from deputy.web.service import live_service

if TYPE_CHECKING:
    import uvicorn

_BIND_HOST = "127.0.0.1"
_HEALTH_PATH = "/healthz"
_HEALTH_MARKER = "deputy"
_PORT_ATTEMPTS = 64
_PROBE_TIMEOUT = 0.5
_START_TIMEOUT = 10.0
_STOP_TIMEOUT = 5.0


@dataclass(frozen=True)
class Endpoint:
    """Where the UI will live, and whether an instance is already serving there."""

    port: int
    already_running: bool


def port_is_free(host: str, port: int) -> bool:
    """True if ``port`` can be bound on ``host`` right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, start: int, *, attempts: int = _PORT_ATTEMPTS) -> int:
    """Return the first free port at or above ``start`` (scanning ``attempts`` ports)."""
    for port in range(start, min(start + attempts, 65536)):
        if port_is_free(host, port):
            return port
    raise RuntimeError(f"no free port found in [{start}, {start + attempts})")


def probe_deputy(host: str, port: int, *, timeout: float = _PROBE_TIMEOUT) -> bool:
    """True if a *Deputy* instance answers on ``host:port`` (via its health marker)."""
    try:
        response = httpx.get(f"http://{host}:{port}{_HEALTH_PATH}", timeout=timeout)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("app") == _HEALTH_MARKER


def resolve_endpoint(host: str, preferred: int, *, attempts: int = _PORT_ATTEMPTS) -> Endpoint:
    """Pick where to serve, treating a re-launch onto a running Deputy as a no-op.

    Fast path: if the preferred port is free, use it. Otherwise, if Deputy is
    already listening there, reuse it; if something else holds it, take the next
    free port so re-launching never errors out.
    """
    if port_is_free(host, preferred):
        return Endpoint(preferred, already_running=False)
    if probe_deputy(host, preferred):
        return Endpoint(preferred, already_running=True)
    return Endpoint(find_free_port(host, preferred + 1, attempts=attempts), already_running=False)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deputy-app", description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="preferred loopback port (auto-picks a free one if busy)",
    )
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama chat model tag")
    parser.add_argument("--ollama-host", default=DEFAULT_HOST, help="Ollama base URL")
    parser.add_argument("--max-steps", type=int, default=8, help="agent step ceiling")
    parser.add_argument("--critic", action="store_true", help="self-check before answering")
    parser.add_argument(
        "--window", action="store_true", help="open a native desktop window (needs the 'app' extra)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="start the server but don't auto-open anything"
    )
    return parser.parse_args(argv)


def _open_browser(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    if not opened:
        print(f"Open {url} in your browser.", file=sys.stderr)


def _open_window(url: str) -> bool:
    """Open a native window via pywebview; return False if it isn't installed.

    This blocks until the window is closed (GUI toolkits must own the main
    thread), which is exactly the lifetime we want the launcher to have.
    """
    try:
        import webview
    except ImportError:
        return False
    webview.create_window("Deputy", url, width=1024, height=760)
    webview.start()
    return True


def _warn_no_pywebview() -> None:
    print(
        "pywebview isn't installed — opening a browser tab instead. "
        "Add native-window support with `uv sync --extra app`.",
        file=sys.stderr,
    )


def _await_started(server: uvicorn.Server, *, timeout: float = _START_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return True
        time.sleep(0.05)
    return server.started


def _block_until_interrupt(server: uvicorn.Server, thread: Thread) -> None:
    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nStopping Deputy…", file=sys.stderr)
        server.should_exit = True
        thread.join(timeout=_STOP_TIMEOUT)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    endpoint = resolve_endpoint(_BIND_HOST, args.port)
    url = f"http://{_BIND_HOST}:{endpoint.port}"

    if endpoint.already_running:
        print(f"Deputy is already running at {url} — opening it.")
        if args.window and _open_window(url):
            return 0
        if args.window:
            _warn_no_pywebview()
        if args.no_browser:
            print(f"Open {url} in your browser.")
        else:
            _open_browser(url)
        return 0

    import uvicorn

    config = DeputyConfig.from_env()
    with live_service(
        config,
        model=args.model,
        host=args.ollama_host,
        max_steps=args.max_steps,
        use_critic=args.critic,
    ) as service:
        app = create_app(service)
        server = uvicorn.Server(
            uvicorn.Config(app, host=_BIND_HOST, port=endpoint.port, log_level="info")
        )
        thread = Thread(target=server.run, name="deputy-web", daemon=True)
        thread.start()
        if not _await_started(server):
            print("error: the web server did not start in time.", file=sys.stderr)
            server.should_exit = True
            thread.join(timeout=_STOP_TIMEOUT)
            return 1

        print(f"Deputy web UI on {url} (audit: {service.audit.path})")
        print("Leave this running; close the window or press Ctrl+C to stop.")

        if args.window and _open_window(url):
            server.should_exit = True
            thread.join(timeout=_STOP_TIMEOUT)
            return 0
        if args.window:
            _warn_no_pywebview()
        if not args.no_browser:
            _open_browser(url)
        _block_until_interrupt(server, thread)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
