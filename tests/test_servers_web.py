"""Web search: response parsing exercised through a mock transport (no network)."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from deputy.mcp import McpHost, memory_connector
from deputy.servers.web import mcp, web_search
from deputy.tools import ApprovalRisk


def _client(payload: Mapping[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_summarizes_abstract_and_related_topics() -> None:
    payload = {
        "AbstractText": "A cat is a small domesticated carnivore.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Cat",
        "RelatedTopics": [
            {"Text": "Kitten - a juvenile cat", "FirstURL": "https://example/kitten"},
            {"Name": "a heading with no text"},
        ],
    }
    with _client(payload) as client:
        result = web_search("cat", client)

    assert "small domesticated carnivore" in result
    assert "en.wikipedia.org/wiki/Cat" in result
    assert "Kitten" in result


def test_reports_when_there_are_no_results() -> None:
    with _client({"RelatedTopics": []}) as client:
        assert "No results" in web_search("asdkjhaskjdh", client)


def test_an_empty_query_short_circuits_without_a_request() -> None:
    def explode(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request should be made for an empty query")

    with httpx.Client(transport=httpx.MockTransport(explode)) as client:
        assert "non-empty" in web_search("   ", client)


def test_mcp_metadata_classifies_web_search_as_external_not_mutating() -> None:
    with McpHost({"web": memory_connector(mcp)}) as host:
        tool = next(tool for tool in host.list_tools() if tool.name == "web_search")

    assert tool.mutating is False
    assert tool.approval_risk is ApprovalRisk.EXTERNAL
