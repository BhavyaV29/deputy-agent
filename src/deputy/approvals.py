"""Approval seam: a callback that can gate a tool call before it runs.

The default auto-approves everything; Phase 4 swaps in a callback that prompts
the user before any write.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from deputy.actions import ToolCall


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""


ApprovalCallback = Callable[[ToolCall], ApprovalDecision]


def auto_approve(call: ToolCall) -> ApprovalDecision:
    return ApprovalDecision(approved=True)
