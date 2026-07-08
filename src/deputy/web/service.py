"""What the web layer runs: a fully-audited agent per request.

:class:`LiveService` owns the process-lifetime resources — the local model
client and the tool registry (built-in MCP servers plus on-device retrieval) —
and builds a fresh agent for each run through :func:`deputy.app.build_agent`, so
the trust surface (policy approvals, audit, local-first routing) is identical to
the CLI. Runs are serialized behind a lock: the model client and MCP servers are
shared, single-user state, and a local UI never needs two runs at once. The web
routes depend only on the :class:`AgentService` protocol, so tests can drive them
with a scripted model and never reach a live Ollama.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from threading import Lock
from typing import Protocol

from deputy.agent import AgentConfig, AgentResult
from deputy.app import assistant_registry, build_agent, open_audit, open_cloud
from deputy.approvals import Prompter
from deputy.audit import AuditLog
from deputy.config import DeputyConfig
from deputy.critic import model_critic
from deputy.events import EventSink
from deputy.model import DEFAULT_HOST, ChatModel, OllamaClient
from deputy.tools import ToolRegistry


class AgentService(Protocol):
    """The seam between the web routes and a running agent."""

    @property
    def audit(self) -> AuditLog: ...

    def run(
        self, goal: str, *, run_id: str, observer: EventSink, prompter: Prompter
    ) -> AgentResult: ...


class LiveService:
    """Run the real agent against the built-in tools and a local Ollama model."""

    def __init__(
        self,
        config: DeputyConfig,
        registry: ToolRegistry,
        local: ChatModel,
        audit: AuditLog,
        *,
        cloud: ChatModel | None = None,
        agent_config: AgentConfig | None = None,
        use_critic: bool = False,
    ) -> None:
        self._config = config
        self._registry = registry
        self._local = local
        self._audit = audit
        self._cloud = cloud
        self._agent_config = agent_config
        self._use_critic = use_critic
        self._lock = Lock()

    @property
    def audit(self) -> AuditLog:
        return self._audit

    def run(
        self, goal: str, *, run_id: str, observer: EventSink, prompter: Prompter
    ) -> AgentResult:
        with self._lock:
            recorder = self._audit.run(run_id)
            agent = build_agent(
                self._config,
                self._registry,
                self._local,
                recorder=recorder,
                prompter=prompter,
                cloud=self._cloud,
                agent_config=self._agent_config,
                critic=model_critic(self._local) if self._use_critic else None,
                observer=observer,
            )
            return agent.run(goal)


@contextmanager
def live_service(
    config: DeputyConfig,
    *,
    model: str,
    host: str = DEFAULT_HOST,
    max_steps: int = 8,
    use_critic: bool = False,
) -> Iterator[LiveService]:
    """Enter the model client and tool registry for the server's lifetime."""
    audit = open_audit(config)
    with ExitStack() as stack:
        local = stack.enter_context(OllamaClient(model=model, host=host))
        cloud = open_cloud(config)
        if cloud is not None:
            stack.enter_context(cloud)
        embedder = stack.enter_context(OllamaClient(model=config.embeddings_model, host=host))
        registry = stack.enter_context(assistant_registry(config, embedder))
        yield LiveService(
            config,
            registry,
            local,
            audit,
            cloud=cloud,
            agent_config=AgentConfig(max_steps=max_steps),
            use_critic=use_critic,
        )
