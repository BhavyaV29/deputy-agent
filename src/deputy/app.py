"""Assemble the real assistant: built-in servers plus on-device retrieval.

This is where configuration becomes a live tool registry. The built-in servers are
launched as subprocesses with their locations passed through the environment; the
retrieval tool is native and shares the injected embedder. Everything the loop then
sees is a uniform registry, so the Phase-2 agent runs unchanged.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from deputy.config import DeputyConfig
from deputy.mcp import McpHost, register_mcp_tools, stdio_connector
from deputy.mcp.host import ServerSpec
from deputy.model import Embedder
from deputy.rag.search import DocRetriever, search_docs_tool
from deputy.servers import calendar, files, notes, web
from deputy.tools import ToolRegistry


def server_specs(config: DeputyConfig) -> dict[str, ServerSpec]:
    specs = {
        "files": _python_server(
            files.__name__, {files.WORKSPACE_ROOT_ENV: str(config.workspace_root)}
        ),
        "notes": _python_server(notes.__name__, {notes.NOTES_PATH_ENV: str(config.notes_path)}),
        "calendar": _python_server(
            calendar.__name__, {calendar.CALENDAR_PATH_ENV: str(config.calendar_path)}
        ),
    }
    if config.web_search_enabled:
        specs["web"] = _python_server(web.__name__, {web.WEB_SEARCH_ENV: "1"})
    return specs


def build_host(config: DeputyConfig) -> McpHost:
    connectors = {name: stdio_connector(spec) for name, spec in server_specs(config).items()}
    return McpHost(connectors)


@contextmanager
def assistant_registry(config: DeputyConfig, embedder: Embedder) -> Iterator[ToolRegistry]:
    config.ensure_data_dir()
    with build_host(config) as host:
        registry = ToolRegistry()
        register_mcp_tools(host, registry)
        registry.register(search_docs_tool(DocRetriever(config.index_path, embedder)))
        yield registry


def _python_server(module: str, env: Mapping[str, str]) -> ServerSpec:
    return ServerSpec(command=sys.executable, args=["-m", module], env=env)
