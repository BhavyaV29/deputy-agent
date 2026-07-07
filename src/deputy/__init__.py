"""Deputy — a private, on-device AI agent.

Public surface of the agent core. Phase-4 seams (audit events, approval
callback) and the model protocol are exported here so callers never reach into
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
from deputy.approvals import ApprovalCallback, ApprovalDecision, auto_approve
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
from deputy.model import ChatModel, ChatResponse, Embedder, Message, OllamaClient
from deputy.prompts import system_prompt
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
    "Critic",
    "CriticResult",
    "Embedder",
    "Event",
    "EventSink",
    "FinalAnswer",
    "Message",
    "OllamaClient",
    "RunFinished",
    "StopReason",
    "Tool",
    "ToolCall",
    "ToolHandler",
    "ToolObserved",
    "ToolRegistry",
    "action_schema",
    "auto_approve",
    "demo_registry",
    "model_critic",
    "object_schema",
    "parse_action",
    "signature",
    "system_prompt",
]
