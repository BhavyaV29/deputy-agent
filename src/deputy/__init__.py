"""Deputy — a private, on-device AI agent.

Public surface of the agent core plus the Phase-3 tools (MCP hosting, built-in
servers, on-device retrieval) and the Phase-4 trust surface: a durable audit log,
a policy-driven approval seam, and a local-first model router with opt-in,
auditable cloud escalation. Everything is exported here so callers never reach into
submodules.
"""

from __future__ import annotations

from deputy.actions import (
    Action,
    ActionParseError,
    FinalAnswer,
    ToolCall,
    action_schema,
    parse_action,
)
from deputy.agent import Agent, AgentConfig, AgentResult
from deputy.approvals import (
    ApprovalCallback,
    ApprovalDecision,
    ApprovalRequest,
    Prompter,
    TrustLevel,
    auto_approve,
    auto_prompter,
    cli_prompter,
    policy_approver,
    recording_approver,
    resolve_trust,
)
from deputy.audit import (
    DEFAULT_REDACT,
    AuditLog,
    AuditRecord,
    RunAudit,
    RunSummary,
    new_run_id,
)
from deputy.config import DeputyConfig
from deputy.critic import Critic, CriticResult, model_critic
from deputy.demo import demo_registry
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    Event,
    EventSink,
    RunFinished,
    StopReason,
    ToolObserved,
    fanout,
)
from deputy.mcp import DiscoveredTool, McpHost, McpToolError, ServerSpec, register_mcp_tools
from deputy.model import ChatModel, ChatResponse, Embedder, Message, OllamaClient
from deputy.prompts import system_prompt
from deputy.rag import Chunk, DocRetriever, VectorStore, chunk_text, search_docs_tool
from deputy.routing import (
    EscalationPolicy,
    ModelRouter,
    OpenAIClient,
    RoutingDecision,
    escalate_all,
    escalate_when_larger_than,
    local_only,
)
from deputy.tools import Tool, ToolHandler, ToolRegistry, object_schema, signature

__version__ = "0.0.0"

__all__ = [
    "DEFAULT_REDACT",
    "Action",
    "ActionDenied",
    "ActionParseError",
    "ActionPlanned",
    "Agent",
    "AgentConfig",
    "AgentResult",
    "AnswerRejected",
    "ApprovalCallback",
    "ApprovalDecision",
    "ApprovalRequest",
    "AuditLog",
    "AuditRecord",
    "ChatModel",
    "ChatResponse",
    "Chunk",
    "Critic",
    "CriticResult",
    "DeputyConfig",
    "DiscoveredTool",
    "DocRetriever",
    "Embedder",
    "EscalationPolicy",
    "Event",
    "EventSink",
    "FinalAnswer",
    "McpHost",
    "McpToolError",
    "Message",
    "ModelRouter",
    "OllamaClient",
    "OpenAIClient",
    "Prompter",
    "RoutingDecision",
    "RunAudit",
    "RunFinished",
    "RunSummary",
    "ServerSpec",
    "StopReason",
    "Tool",
    "ToolCall",
    "ToolHandler",
    "ToolObserved",
    "ToolRegistry",
    "TrustLevel",
    "VectorStore",
    "action_schema",
    "auto_approve",
    "auto_prompter",
    "chunk_text",
    "cli_prompter",
    "demo_registry",
    "escalate_all",
    "escalate_when_larger_than",
    "fanout",
    "local_only",
    "model_critic",
    "new_run_id",
    "object_schema",
    "parse_action",
    "policy_approver",
    "recording_approver",
    "register_mcp_tools",
    "resolve_trust",
    "search_docs_tool",
    "signature",
    "system_prompt",
]
