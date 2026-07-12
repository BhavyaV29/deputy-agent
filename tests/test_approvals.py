"""The approval gate: policy, trust overrides, prompters, and loop feedback."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

from deputy.actions import ToolCall
from deputy.agent import Agent
from deputy.approvals import (
    ApprovalDecision,
    ApprovalRequest,
    TrustLevel,
    auto_prompter,
    cli_prompter,
    policy_approver,
    recording_approver,
    resolve_trust,
)
from deputy.events import ActionDenied
from deputy.model import ChatResponse, Message
from deputy.tools import ApprovalRisk, Tool, ToolRegistry, object_schema


def _reader(args: Mapping[str, Any]) -> str:
    return "read"


def _writer(recorder: list[str]) -> Tool:
    def handler(args: Mapping[str, Any]) -> str:
        recorder.append(str(args["text"]))
        return "written"

    return Tool("add_note", "save a note", object_schema(text={"type": "string"}), handler, True)


def _registry(recorder: list[str] | None = None) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool("search", "look up", object_schema(q={"type": "string"}), _reader),
            _writer(recorder if recorder is not None else []),
        ]
    )


class _Prompter:
    """A programmatic prompter: canned decision, remembers what it was asked."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.seen: list[ApprovalRequest] = []

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        self.seen.append(request)
        return ApprovalDecision(self._approved, "scripted")


class _ScriptedModel:
    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def chat(
        self,
        messages: Sequence[Message],
        *,
        schema: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        reply = self._replies[self.calls]
        self.calls += 1
        return ChatResponse(reply)


def _tool(name: str, **args: Any) -> str:
    return json.dumps({"tool": name, "args": args})


def _final(text: str) -> str:
    return json.dumps({"final": text})


def test_read_only_tools_are_auto_approved_without_prompting() -> None:
    prompter = _Prompter(approved=False)  # would deny if consulted
    approve = policy_approver(_registry(), prompter)

    decision = approve(ToolCall("search", {"q": "cats"}))

    assert decision.approved is True
    assert "read-only" in decision.reason
    assert prompter.seen == []


def test_mutating_tools_require_approval() -> None:
    prompter = _Prompter(approved=True)
    approve = policy_approver(_registry(), prompter)

    decision = approve(ToolCall("add_note", {"text": "hi"}))

    assert decision.approved is True
    assert len(prompter.seen) == 1
    assert prompter.seen[0].mutating is True
    assert prompter.seen[0].call.tool == "add_note"


def test_external_tools_require_approval_without_being_marked_mutating() -> None:
    registry = ToolRegistry(
        [
            Tool(
                "web_search",
                "search the public web",
                object_schema(q={"type": "string"}),
                _reader,
                approval_risk=ApprovalRisk.EXTERNAL,
            )
        ]
    )
    prompter = _Prompter(approved=True)

    decision = policy_approver(registry, prompter)(ToolCall("web_search", {"q": "cats"}))

    assert decision.approved is True
    assert len(prompter.seen) == 1
    request = prompter.seen[0]
    assert request.mutating is False
    assert request.risk is ApprovalRisk.EXTERNAL
    assert "external service" in request.reason


def test_unknown_tool_risk_fails_closed_to_a_prompt() -> None:
    registry = ToolRegistry(
        [
            Tool(
                "ambiguous",
                "tool with incomplete metadata",
                object_schema(),
                _reader,
                approval_risk=ApprovalRisk.UNKNOWN,
            )
        ]
    )
    prompter = _Prompter(approved=False)

    decision = policy_approver(registry, prompter)(ToolCall("ambiguous", {}))

    assert decision.approved is False
    assert prompter.seen[0].risk is ApprovalRisk.UNKNOWN
    assert "safety annotations" in prompter.seen[0].reason


def test_denied_write_is_not_executed_and_feeds_back_into_the_loop() -> None:
    recorder: list[str] = []
    model = _ScriptedModel([_tool("add_note", text="secret"), _final("done")])
    approve = policy_approver(_registry(recorder), auto_prompter(approved=False))

    result = Agent(model, _registry(recorder), approve=approve).run("save it")

    assert recorder == []  # the write never ran
    assert result.answer == "done"  # the loop recovered on the next step
    denials = [event for event in result.events if isinstance(event, ActionDenied)]
    assert len(denials) == 1


def test_trust_override_can_wave_through_a_write() -> None:
    prompter = _Prompter(approved=False)
    approve = policy_approver(_registry(), prompter, trust={"add_note": TrustLevel.ALLOW})

    decision = approve(ToolCall("add_note", {"text": "hi"}))

    assert decision.approved is True
    assert "explicit per-tool policy" in decision.reason
    assert prompter.seen == []  # override short-circuits the prompt


def test_allow_override_can_wave_through_external_access() -> None:
    tool = Tool(
        "web_search",
        "search the public web",
        object_schema(q={"type": "string"}),
        _reader,
        approval_risk=ApprovalRisk.EXTERNAL,
    )
    prompter = _Prompter(approved=False)

    decision = policy_approver(
        ToolRegistry([tool]), prompter, trust={"web_search": TrustLevel.ALLOW}
    )(ToolCall("web_search", {"q": "x"}))

    assert decision.approved is True
    assert "explicit per-tool policy" in decision.reason
    assert prompter.seen == []


def test_prompt_override_can_gate_a_local_read() -> None:
    prompter = _Prompter(approved=True)
    approve = policy_approver(_registry(), prompter, trust={"search": TrustLevel.PROMPT})

    decision = approve(ToolCall("search", {"q": "x"}))

    assert decision.approved is True
    assert prompter.seen[0].risk is ApprovalRisk.LOCAL_READ
    assert "Per-tool policy" in prompter.seen[0].reason


def test_trust_override_can_block_a_read() -> None:
    approve = policy_approver(_registry(), auto_prompter(), trust={"search": TrustLevel.DENY})
    decision = approve(ToolCall("search", {"q": "x"}))
    assert decision.approved is False
    assert "denies" in decision.reason


def test_unknown_tool_is_denied() -> None:
    decision = policy_approver(_registry(), auto_prompter())(ToolCall("ghost", {}))
    assert decision.approved is False
    assert "unknown tool" in decision.reason


def test_resolve_trust_defaults_and_overrides() -> None:
    assert resolve_trust(ApprovalRisk.LOCAL_READ, override=None) is TrustLevel.ALLOW
    assert resolve_trust(ApprovalRisk.MUTATION, override=None) is TrustLevel.PROMPT
    assert resolve_trust(ApprovalRisk.EXTERNAL, override=None) is TrustLevel.PROMPT
    assert resolve_trust(ApprovalRisk.UNKNOWN, override=None) is TrustLevel.PROMPT
    assert resolve_trust(ApprovalRisk.MUTATION, override=TrustLevel.ALLOW) is TrustLevel.ALLOW


def test_cli_prompter_accepts_and_declines() -> None:
    out = io.StringIO()
    request = ApprovalRequest(
        ToolCall("add_note", {"text": "hi"}),
        True,
        "save a note",
        risk=ApprovalRisk.MUTATION,
        reason="This tool can modify local state.",
    )

    yes = cli_prompter(read=lambda _: "y", out=out)(request)
    no = cli_prompter(read=lambda _: "", out=out)(request)

    assert yes.approved is True
    assert no.approved is False
    assert "add_note" in out.getvalue()
    assert "[approval] write" in out.getvalue()


def test_cli_prompter_labels_external_access_and_explains_the_risk() -> None:
    out = io.StringIO()
    request = ApprovalRequest(
        ToolCall("web_search", {"query": "cats"}),
        False,
        "search the public web",
        risk=ApprovalRisk.EXTERNAL,
        reason="This tool can send data to an external service.",
    )

    cli_prompter(read=lambda _: "", out=out)(request)

    assert "[approval] external access" in out.getvalue()
    assert "external service" in out.getvalue()


def test_recording_approver_reports_every_decision() -> None:
    seen: list[tuple[str, bool]] = []
    approve = recording_approver(
        policy_approver(_registry(), auto_prompter()),
        lambda call, decision: seen.append((call.tool, decision.approved)),
    )

    approve(ToolCall("search", {"q": "x"}))
    approve(ToolCall("add_note", {"text": "y"}))

    assert seen == [("search", True), ("add_note", True)]
