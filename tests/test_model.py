"""OllamaClient wire behavior, exercised through a mock transport (no network)."""

from __future__ import annotations

import json

import httpx

from deputy.model import Message, OllamaClient


def _client(handler: httpx.MockTransport) -> OllamaClient:
    return OllamaClient("qwen2.5:3b", transport=handler)


def test_chat_builds_the_payload_and_parses_the_reply() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"final": "hi"}'}})

    with _client(httpx.MockTransport(handler)) as client:
        response = client.chat([Message("user", "hey")], schema={"type": "object"}, seed=7)

    assert response.text == '{"final": "hi"}'
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen2.5:3b"
    assert body["messages"] == [{"role": "user", "content": "hey"}]
    assert body["stream"] is False
    assert body["format"] == {"type": "object"}
    assert body["options"]["seed"] == 7
    assert str(captured["url"]).endswith("/api/chat")


def test_chat_omits_format_when_no_schema_is_given() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "plain"}})

    with _client(httpx.MockTransport(handler)) as client:
        response = client.chat([Message("user", "x")])

    assert response.text == "plain"
    body = captured["body"]
    assert isinstance(body, dict)
    assert "format" not in body


def test_embed_returns_the_first_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/api/embed")
        assert json.loads(request.content)["input"] == "hello"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    with _client(httpx.MockTransport(handler)) as client:
        assert client.embed("hello") == [0.1, 0.2, 0.3]
