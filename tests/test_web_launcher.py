"""Unit tests for the ``deputy-app`` launcher's port selection and probing.

These exercise the pure networking logic on real ephemeral loopback sockets (no
live server, no Ollama). The ``/healthz`` probe against a real Deputy instance is
covered in :mod:`tests.test_web`, where the uvicorn harness already exists.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from deputy.web import launcher
from deputy.web.launcher import (
    Endpoint,
    find_free_port,
    port_is_free,
    probe_deputy,
    resolve_endpoint,
)

HOST = "127.0.0.1"


@contextmanager
def _occupied(host: str = HOST) -> Iterator[int]:
    """Bind + listen on an ephemeral port; yield it while the socket is held."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(1)
        yield int(sock.getsockname()[1])


def _free_port(host: str = HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def test_port_is_free_true_when_nothing_listens() -> None:
    assert port_is_free(HOST, _free_port()) is True


def test_port_is_free_false_when_occupied() -> None:
    with _occupied() as port:
        assert port_is_free(HOST, port) is False


def test_find_free_port_skips_the_occupied_one() -> None:
    with _occupied() as port:
        found = find_free_port(HOST, port)
        assert found > port
        assert port_is_free(HOST, found) is True


def test_find_free_port_raises_when_none_available() -> None:
    with _occupied() as port, pytest.raises(RuntimeError):
        find_free_port(HOST, port, attempts=1)


def test_probe_deputy_false_when_nothing_listens() -> None:
    assert probe_deputy(HOST, _free_port(), timeout=0.2) is False


def test_probe_deputy_false_for_non_http_listener() -> None:
    # A raw TCP socket that never speaks HTTP: the probe must fail/time out and
    # report "not Deputy" rather than raising.
    with _occupied() as port:
        assert probe_deputy(HOST, port, timeout=0.2) is False


def test_resolve_endpoint_uses_preferred_when_free() -> None:
    port = _free_port()
    assert resolve_endpoint(HOST, port) == Endpoint(port, already_running=False)


def test_resolve_endpoint_moves_off_a_non_deputy_port() -> None:
    with _occupied() as port:
        endpoint = resolve_endpoint(HOST, port)
        assert endpoint.already_running is False
        assert endpoint.port != port
        assert port_is_free(HOST, endpoint.port) is True


def test_resolve_endpoint_reuses_a_running_deputy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "probe_deputy", lambda *args, **kwargs: True)
    with _occupied() as port:
        assert resolve_endpoint(HOST, port) == Endpoint(port, already_running=True)
