"""The audit trail: durable JSONL persistence, a query API, and redaction."""

from __future__ import annotations

import json
from pathlib import Path

from deputy.actions import FinalAnswer, ToolCall
from deputy.approvals import ApprovalDecision
from deputy.audit import AuditLog
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    RunFinished,
    StopReason,
    ToolObserved,
)
from deputy.model import Message
from deputy.routing import RoutingDecision


def test_every_event_kind_persists_and_reads_back_by_run(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    run = log.run("run-1")

    call = ToolCall("add_note", {"text": "buy milk"})
    run(ActionPlanned(1, call))
    run(ToolObserved(1, call, "saved", ok=True))
    run(ActionDenied(2, ToolCall("rm", {"path": "/etc"}), "policy denies 'rm'"))
    run(AnswerRejected(2, "draft", "too short"))
    run(RunFinished(3, "done", StopReason.ANSWERED))

    kinds = [record.kind for record in log.by_run("run-1")]
    assert kinds == [
        "action_planned",
        "tool_observed",
        "action_denied",
        "answer_rejected",
        "run_finished",
    ]
    planned = log.by_run("run-1")[0]
    assert planned.data["action"] == {"tool": "add_note", "args": {"text": "buy milk"}}
    assert planned.run_id == "run-1"
    assert planned.ts  # ISO-8601 timestamp


def test_records_are_append_only_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.run("a")(RunFinished(1, "first", StopReason.ANSWERED))
    log.run("b")(RunFinished(1, "second", StopReason.ANSWERED))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["run_id"] for line in lines] == ["a", "b"]


def test_recent_and_run_summaries(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.run("old")(RunFinished(1, "answer-old", StopReason.ANSWERED))
    second = log.run("new")
    second(ActionPlanned(1, FinalAnswer("hi")))
    second(RunFinished(1, "answer-new", StopReason.MAX_STEPS))

    assert [r.run_id for r in log.recent(2)] == ["new", "new"]

    summaries = {s.run_id: s for s in log.runs()}
    assert summaries["old"].events == 1
    assert summaries["old"].answer == "answer-old"
    assert summaries["new"].events == 2
    assert summaries["new"].reason == "max_steps"
    assert summaries["new"].started <= summaries["new"].ended


def test_sensitive_arg_fields_are_redacted(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    call = ToolCall("login", {"user": "sam", "api_key": "sk-secret", "nested": {"token": "t0p"}})

    log.run("r")(ActionPlanned(1, call))

    args = log.by_run("r")[0].data["action"]["args"]
    assert args["user"] == "sam"
    assert args["api_key"] == "[redacted]"
    assert args["nested"]["token"] == "[redacted]"


def test_redaction_fields_are_configurable(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", redact_fields=frozenset({"ssn"}))
    call = ToolCall("file", {"ssn": "123-45-6789", "api_key": "left-alone"})

    log.run("r")(ActionPlanned(1, call))

    args = log.by_run("r")[0].data["action"]["args"]
    assert args["ssn"] == "[redacted]"
    assert args["api_key"] == "left-alone"  # not in the configured set


def test_long_tool_observations_are_summarized(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    observation = "x" * 5000

    log.run("r")(ToolObserved(1, ToolCall("read_file", {}), observation, ok=True))

    data = log.by_run("r")[0].data
    assert data["chars"] == 5000
    assert len(data["observation"]) < 5000
    assert data["observation"].endswith("...")


def test_approval_decisions_are_recorded_with_redaction(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    call = ToolCall("add_note", {"text": "hi", "password": "hunter2"})

    log.run("r").record_approval(call, ApprovalDecision(approved=True, reason="auto: read-only"))

    record = log.by_run("r")[0]
    assert record.kind == "approval"
    assert record.data["approved"] is True
    assert record.data["reason"] == "auto: read-only"
    assert record.data["args"]["password"] == "[redacted]"


def test_routing_records_exactly_what_crossed_the_boundary(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    messages = (Message("system", "sys"), Message("user", "q" * 1000))
    decision = RoutingDecision("too big", "openai", "gpt-4o-mini", messages)

    log.run("r").record_routing(decision)

    data = log.by_run("r")[0].data
    assert data["reason"] == "too big"
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["message_count"] == 2
    assert data["chars"] == 1003  # data-minimization: full size recorded, content previewed
    assert len(data["messages"][1]["content"]) < 1000
    assert len(data["digest"]) == 64  # sha256 fingerprint of the exact payload sent
