"""Assemble the real assistant: built-in servers, retrieval, and the trust surface.

This is where configuration becomes a live tool registry and a wired-up agent. The
built-in servers are launched as subprocesses with their locations passed through
the environment; the retrieval tool is native and shares the injected embedder.
Everything the loop sees is a uniform registry, so the Phase-2 agent runs unchanged
— now behind a local-first router, a policy approver, and an audit trail, all on by
default and all fully on-device unless the cloud is explicitly enabled.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from deputy.agent import Agent, AgentConfig
from deputy.approvals import Prompter, policy_approver, recording_approver
from deputy.audit import AuditLog, RunAudit
from deputy.config import DeputyConfig
from deputy.critic import Critic
from deputy.events import EventSink, fanout
from deputy.mcp import McpHost, register_mcp_tools, stdio_connector
from deputy.mcp.host import ServerSpec
from deputy.model import ChatModel, Embedder
from deputy.rag.search import DocRetriever, search_docs_tool
from deputy.routing import ModelRouter, OpenAIClient, escalate_when_larger_than
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


def open_audit(config: DeputyConfig) -> AuditLog:
    config.ensure_data_dir()
    return AuditLog(config.audit_path, redact_fields=config.audit_redact)


def open_cloud(config: DeputyConfig) -> OpenAIClient | None:
    """Build the cloud client only when escalation is genuinely opted into."""
    if not config.cloud_ready:
        return None
    assert config.cloud_api_key is not None  # guaranteed by cloud_ready
    return OpenAIClient(
        config.cloud_model, api_key=config.cloud_api_key, base_url=config.cloud_base_url
    )


def build_router(
    config: DeputyConfig,
    local: ChatModel,
    cloud: ChatModel | None,
    *,
    on_route: RunAudit | None = None,
) -> ChatModel:
    if cloud is None:
        return local  # fully local: no router, no way off the device
    return ModelRouter(
        local,
        cloud,
        policy=escalate_when_larger_than(config.cloud_escalate_chars),
        on_route=None if on_route is None else on_route.record_routing,
        provider="openai",
        model=config.cloud_model,
    )


def build_agent(
    config: DeputyConfig,
    registry: ToolRegistry,
    local: ChatModel,
    *,
    recorder: RunAudit,
    prompter: Prompter,
    cloud: ChatModel | None = None,
    agent_config: AgentConfig | None = None,
    critic: Critic | None = None,
    observer: EventSink | None = None,
) -> Agent:
    """Wire model + approvals + audit: local-first, risky tools gated."""
    model = build_router(config, local, cloud, on_route=recorder)
    approve = recording_approver(
        policy_approver(registry, prompter, trust=config.trust_overrides),
        recorder.record_approval,
    )
    on_event = recorder if observer is None else fanout(recorder, observer)
    return Agent(
        model,
        registry,
        config=agent_config,
        approve=approve,
        critic=critic,
        on_event=on_event,
    )


def _python_server(module: str, env: Mapping[str, str]) -> ServerSpec:
    return ServerSpec(command=sys.executable, args=["-m", module], env=env)
