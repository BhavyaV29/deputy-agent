"""Approval seam: gate a tool call before it runs.

The loop calls one :data:`ApprovalCallback` per tool call. ``auto_approve`` is
available for isolated/demo use; the assembled app uses a policy-driven approver
that waves through explicitly local read-only tools, requires approval for
mutations, external access, and unclassified tools, and honours per-tool trust
overrides. Crucially, *deciding* whether approval is needed is split from
*obtaining* it: when a call needs sign-off the approver hands an
:class:`ApprovalRequest` to a :data:`Prompter`. CLI, non-interactive, and browser
prompters all implement that same seam.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TextIO

from deputy.actions import ToolCall
from deputy.tools import ApprovalRisk, ToolRegistry


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""


ApprovalCallback = Callable[[ToolCall], ApprovalDecision]


def auto_approve(call: ToolCall) -> ApprovalDecision:
    return ApprovalDecision(approved=True)


class TrustLevel(StrEnum):
    ALLOW = "allow"  # run without asking
    PROMPT = "prompt"  # ask the operator/UI first
    DENY = "deny"  # never run


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending, human-answerable question: may Deputy run this call?"""

    call: ToolCall
    mutating: bool
    description: str
    risk: ApprovalRisk = ApprovalRisk.UNKNOWN
    reason: str = ""


Prompter = Callable[[ApprovalRequest], ApprovalDecision]


def resolve_trust(tool_risk: ApprovalRisk, override: TrustLevel | None) -> TrustLevel:
    """Explicit per-tool trust wins; otherwise only confined local reads are allowed."""
    if override is not None:
        return override
    return TrustLevel.ALLOW if tool_risk is ApprovalRisk.LOCAL_READ else TrustLevel.PROMPT


def policy_approver(
    registry: ToolRegistry,
    prompter: Prompter,
    *,
    trust: Mapping[str, TrustLevel] | None = None,
) -> ApprovalCallback:
    """Auto-approve explicit local reads and prompt for every other risk by default."""
    overrides = dict(trust or {})

    def approve(call: ToolCall) -> ApprovalDecision:
        try:
            tool = registry.get(call.tool)
        except KeyError:
            return ApprovalDecision(False, f"unknown tool {call.tool!r}")

        level = resolve_trust(tool.approval_risk, overrides.get(call.tool))
        if level is TrustLevel.DENY:
            return ApprovalDecision(False, f"policy denies {call.tool!r}")
        if level is TrustLevel.ALLOW:
            basis = (
                "trusted by explicit per-tool policy"
                if call.tool in overrides
                else "confined local read-only tool"
            )
            return ApprovalDecision(True, f"auto-approved: {basis}")
        return prompter(
            ApprovalRequest(
                call,
                tool.mutating,
                tool.description,
                risk=tool.approval_risk,
                reason=_prompt_reason(tool.approval_risk),
            )
        )

    return approve


def recording_approver(
    inner: ApprovalCallback, record: Callable[[ToolCall, ApprovalDecision], None]
) -> ApprovalCallback:
    """Wrap an approver so every decision it makes is handed to ``record``."""

    def approve(call: ToolCall) -> ApprovalDecision:
        decision = inner(call)
        record(call, decision)
        return decision

    return approve


_YES = frozenset({"y", "yes"})


def cli_prompter(*, read: Callable[[str], str] = input, out: TextIO = sys.stderr) -> Prompter:
    """Interactive approver: describe the pending call, then read a y/N answer."""

    def prompt(request: ApprovalRequest) -> ApprovalDecision:
        print(_describe(request), file=out)
        approved = read("approve? [y/N] ").strip().lower() in _YES
        reason = "approved by operator" if approved else "declined by operator"
        return ApprovalDecision(approved, reason)

    return prompt


def auto_prompter(*, approved: bool = True, announce: TextIO | None = None) -> Prompter:
    """Non-interactive approver for scripting/tests; optionally narrates decisions."""

    def prompt(request: ApprovalRequest) -> ApprovalDecision:
        if announce is not None:
            verb = "auto-approved" if approved else "auto-denied"
            print(f"[approval] {verb} `{request.call.tool}` (non-interactive)", file=announce)
        reason = "non-interactive approval" if approved else "non-interactive denial"
        return ApprovalDecision(approved, reason)

    return prompt


def _describe(request: ApprovalRequest) -> str:
    args = ", ".join(f"{key}={value!r}" for key, value in request.call.args.items())
    if request.risk is ApprovalRisk.EXTERNAL:
        tag = "external access"
    elif request.mutating or request.risk is ApprovalRisk.MUTATION:
        tag = "write"
    elif request.risk is ApprovalRisk.UNKNOWN:
        tag = "unclassified action"
    else:
        tag = "read"
    details = " — ".join(part for part in (request.reason, request.description) if part)
    suffix = f" — {details}" if details else ""
    return f"[approval] {tag} `{request.call.tool}({args})`{suffix}"


def _prompt_reason(risk: ApprovalRisk) -> str:
    return {
        ApprovalRisk.MUTATION: "This tool can modify local state.",
        ApprovalRisk.EXTERNAL: "This tool can send data to an external service.",
        ApprovalRisk.UNKNOWN: "This tool lacks complete safety annotations.",
        ApprovalRisk.LOCAL_READ: "Per-tool policy requires approval for this confined local read.",
    }[risk]
