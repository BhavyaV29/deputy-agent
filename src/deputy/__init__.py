"""Deputy — a private, on-device AI agent.

Public surface of the agent core plus the Phase-3 additions: MCP tool hosting,
the built-in tool servers, and on-device retrieval. Phase-4 seams (audit events,
approval callback) and the model protocol are exported here so callers never reach
into submodules.
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
from deputy.approvals import ApprovalCallback, ApprovalDecision, auto_approve
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
)
from deputy.mcp import DiscoveredTool, McpHost, McpToolError, ServerSpec, register_mcp_tools
from deputy.model import ChatModel, ChatResponse, Embedder, Message, OllamaClient
from deputy.prompts import system_prompt
from deputy.rag import Chunk, DocRetriever, VectorStore, chunk_text, search_docs_tool
from deputy.tools import Tool, ToolHandler, ToolRegistry, object_schema, signature

__version__ = "0.0.0"

__all__ = [
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
    "ChatModel",
    "ChatResponse",
    "Chunk",
    "Critic",
    "CriticResult",
    "DeputyConfig",
    "DiscoveredTool",
    "DocRetriever",
    "Embedder",
    "Event",
    "EventSink",
    "FinalAnswer",
    "McpHost",
    "McpToolError",
    "Message",
    "OllamaClient",
    "RunFinished",
    "ServerSpec",
    "StopReason",
    "Tool",
    "ToolCall",
    "ToolHandler",
    "ToolObserved",
    "ToolRegistry",
    "VectorStore",
    "action_schema",
    "auto_approve",
    "chunk_text",
    "demo_registry",
    "model_critic",
    "object_schema",
    "parse_action",
    "register_mcp_tools",
    "search_docs_tool",
    "signature",
    "system_prompt",
]
