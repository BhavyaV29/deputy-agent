"""Model routing: local by default, cloud only on explicit, audited opt-in."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from deputy.model import ChatResponse, Message
from deputy.routing import (
    ModelRouter,
    OpenAIClient,
    RoutingDecision,
    escalate_all,
    escalate_when_larger_than,
)


class FakeModel:
    """A ChatModel that returns a fixed reply and remembers every prompt."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return ChatResponse(self._reply)


def test_default_stays_local_and_never_calls_cloud() -> None:
    local, cloud = FakeModel("local"), FakeModel("cloud")
    routes: list[RoutingDecision] = []
    router = ModelRouter(local, cloud, on_route=routes.append)

    response = router.chat([Message("user", "hello")])

    assert response.text == "local"
    assert cloud.calls == []
    assert routes == []


def test_without_a_cloud_client_it_cannot_escalate() -> None:
    local = FakeModel("local")
    # Even an always-escalate policy is inert when no cloud model was wired in.
    router = ModelRouter(local, cloud=None, policy=escalate_all("try anyway"))

    assert router.chat([Message("user", "x" * 10_000)]).text == "local"


def test_escalation_only_on_opt_in_and_records_the_boundary() -> None:
    local, cloud = FakeModel("local"), FakeModel("cloud")
    routes: list[RoutingDecision] = []
    router = ModelRouter(
        local, cloud, policy=escalate_all("needs cloud"), on_route=routes.append, model="gpt-4o"
    )

    messages = [Message("system", "sys"), Message("user", "hard question")]
    response = router.chat(messages)

    assert response.text == "cloud"
    assert local.calls == []
    assert len(routes) == 1
    assert routes[0].reason == "needs cloud"
    assert routes[0].model == "gpt-4o"
    assert routes[0].messages == tuple(messages)  # exactly what crossed the boundary


def test_minimizer_shapes_what_leaves_the_device() -> None:
    local, cloud = FakeModel("local"), FakeModel("cloud")
    routes: list[RoutingDecision] = []
    router = ModelRouter(
        local,
        cloud,
        policy=escalate_all(),
        on_route=routes.append,
        minimize=lambda messages: list(messages)[-1:],  # send only the last turn
    )

    router.chat([Message("system", "secret system prompt"), Message("user", "just this")])

    assert [m.content for m in cloud.calls[0]] == ["just this"]
    assert routes[0].messages == (Message("user", "just this"),)


def test_escalate_when_larger_than_threshold() -> None:
    local, cloud = FakeModel("local"), FakeModel("cloud")
    router = ModelRouter(local, cloud, policy=escalate_when_larger_than(20))

    router.chat([Message("user", "short")])  # 5 chars -> local
    router.chat([Message("user", "x" * 50)])  # 50 chars -> cloud

    assert len(local.calls) == 1
    assert len(cloud.calls) == 1


def test_openai_client_builds_request_and_parses_reply() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"final": "ok"}'}}]})

    client = OpenAIClient("gpt-4o-mini", api_key="sk-test", transport=httpx.MockTransport(handler))
    with client:
        response = client.chat([Message("user", "hi")], schema={"type": "object"}, seed=3)

    assert response.text == '{"final": "ok"}'
    assert captured["auth"] == "Bearer sk-test"
    assert str(captured["url"]).endswith("/chat/completions")
    body = captured["body"]
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["seed"] == 3
    assert body["response_format"] == {"type": "json_object"}


def test_openai_client_omits_response_format_without_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain"}}]})

    with OpenAIClient("m", api_key="k", transport=httpx.MockTransport(handler)) as client:
        assert client.chat([Message("user", "x")]).text == "plain"
