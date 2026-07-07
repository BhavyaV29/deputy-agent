"""Opt-in web search — the only tool that reaches the network.

It is disabled by default and never registered unless ``DEPUTY_WEB_SEARCH_ENABLED``
is set, keeping Deputy fully on-device out of the box. The lookup uses DuckDuckGo's
keyless instant-answer endpoint and the HTTP client is injected so the parsing can
be exercised without touching the network.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

WEB_SEARCH_ENV = "DEPUTY_WEB_SEARCH_ENABLED"
_ENDPOINT = "https://api.duckduckgo.com/"
_MAX_RESULTS = 5


def web_search(query: str, client: httpx.Client) -> str:
    term = query.strip()
    if not term:
        return "Provide a non-empty query."
    response = client.get(_ENDPOINT, params={"q": term, "format": "json", "no_html": "1"})
    response.raise_for_status()
    return _summarize(response.json())


def _summarize(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    abstract = str(payload.get("AbstractText") or "").strip()
    if abstract:
        source = str(payload.get("AbstractURL") or "").strip()
        lines.append(f"{abstract} ({source})" if source else abstract)
    for topic in _related(payload.get("RelatedTopics", [])):
        lines.append(topic)
        if len(lines) >= _MAX_RESULTS:
            break
    return "\n".join(lines) if lines else "No results."


def _related(topics: list[Any]) -> list[str]:
    out: list[str] = []
    for topic in topics:
        if isinstance(topic, dict) and (text := str(topic.get("Text") or "").strip()):
            url = str(topic.get("FirstURL") or "").strip()
            out.append(f"{text} ({url})" if url else text)
    return out


mcp = FastMCP("web")


@mcp.tool(
    name="web_search",
    description="Search the web for a query and return short result summaries.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
def web_search_tool(query: str) -> str:
    with httpx.Client(timeout=15.0) as client:
        return web_search(query, client)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
