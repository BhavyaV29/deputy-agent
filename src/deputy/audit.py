"""A durable, append-only audit trail — Deputy's memory of what it did and why.

Every meaningful moment is written as one JSON line under ``data/``: the actions
the model planned, the observations tools returned, approval decisions, denials,
and any time a request escalated to the cloud (with exactly what crossed the
boundary). JSONL is deliberate — the log is plain text the user can ``tail`` while
Deputy works, which is itself part of the trust surface. The write side is an
:data:`~deputy.events.EventSink` (plus approval/routing hooks); the read side is a
small query API the Phase-5 UI consumes.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deputy.actions import Action, FinalAnswer, ToolCall
from deputy.approvals import ApprovalDecision
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    Event,
    RunFinished,
    ToolObserved,
)
from deputy.model import Message
from deputy.routing import RoutingDecision

DEFAULT_REDACT: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "credential",
    }
)
REDACTED = "[redacted]"

_OBSERVATION_CHARS = 1000  # tool output is summarized so the log stays lean
_PREVIEW_CHARS = 200  # per-message preview of anything sent to the cloud


@dataclass(frozen=True)
class AuditRecord:
    ts: str  # ISO-8601, UTC, millisecond precision — lexically sortable
    run_id: str
    kind: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started: str
    ended: str
    events: int
    answer: str | None
    reason: str | None


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


class AuditLog:
    """The store: durable appends plus a query API keyed by run and recency."""

    def __init__(self, path: Path, *, redact_fields: frozenset[str] = DEFAULT_REDACT) -> None:
        self._path = path
        self._redact = frozenset(field.lower() for field in redact_fields)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def redact_fields(self) -> frozenset[str]:
        return self._redact

    def run(self, run_id: str | None = None) -> RunAudit:
        """A recorder bound to one run — the object the agent uses as its sink."""
        return RunAudit(self, run_id or new_run_id())

    def redact(self, value: Any) -> Any:
        return _redact(value, self._redact)

    def append(self, record: AuditRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"ts": record.ts, "run_id": record.run_id, "kind": record.kind, "data": record.data},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())  # an audit record the user can't rely on isn't one

    def records(self) -> Iterator[AuditRecord]:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    yield _parse(stripped)

    def by_run(self, run_id: str) -> list[AuditRecord]:
        return [record for record in self.records() if record.run_id == run_id]

    def recent(self, limit: int = 50) -> list[AuditRecord]:
        return list(self.records())[-limit:]

    def runs(self) -> list[RunSummary]:
        grouped: dict[str, list[AuditRecord]] = {}
        for record in self.records():
            grouped.setdefault(record.run_id, []).append(record)
        return [_summarize(run_id, records) for run_id, records in grouped.items()]


class RunAudit:
    """The write side for one run: an ``EventSink`` plus approval/routing hooks."""

    def __init__(self, log: AuditLog, run_id: str) -> None:
        self._log = log
        self._run_id = run_id

    @property
    def run_id(self) -> str:
        return self._run_id

    def __call__(self, event: Event) -> None:
        kind, data = self._event(event)
        self._write(kind, data)

    def record_approval(self, call: ToolCall, decision: ApprovalDecision) -> None:
        self._write(
            "approval",
            {
                "tool": call.tool,
                "args": self._log.redact(call.args),
                "approved": decision.approved,
                "reason": decision.reason,
            },
        )

    def record_routing(self, decision: RoutingDecision) -> None:
        self._write(
            "routing",
            {
                "reason": decision.reason,
                "provider": decision.provider,
                "model": decision.model,
                "messages": [
                    {"role": m.role, "content": _preview(m.content)} for m in decision.messages
                ],
                "message_count": len(decision.messages),
                "chars": sum(len(m.content) for m in decision.messages),
                "digest": _digest(decision.messages),
            },
        )

    def _event(self, event: Event) -> tuple[str, dict[str, Any]]:
        match event:
            case ActionPlanned(step, action):
                return "action_planned", {"step": step, "action": self._action(action)}
            case ToolObserved(step, call, observation, ok):
                return "tool_observed", {
                    "step": step,
                    "tool": call.tool,
                    "ok": ok,
                    **_summarize_observation(observation),
                }
            case ActionDenied(step, call, reason):
                return "action_denied", {
                    "step": step,
                    "tool": call.tool,
                    "args": self._log.redact(call.args),
                    "reason": reason,
                }
            case AnswerRejected(step, answer, feedback):
                return "answer_rejected", {"step": step, "answer": answer, "feedback": feedback}
            case RunFinished(step, answer, reason):
                return "run_finished", {"step": step, "answer": answer, "reason": str(reason)}

    def _action(self, action: Action) -> dict[str, Any]:
        if isinstance(action, FinalAnswer):
            return {"final": action.text}
        return {"tool": action.tool, "args": self._log.redact(action.args)}

    def _write(self, kind: str, data: Mapping[str, Any]) -> None:
        self._log.append(AuditRecord(ts=_now(), run_id=self._run_id, kind=kind, data=data))


def _redact(value: Any, fields: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if str(key).lower() in fields else _redact(val, fields)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, fields) for item in value]
    return value


def _summarize_observation(observation: str) -> dict[str, Any]:
    return {"observation": _preview(observation, _OBSERVATION_CHARS), "chars": len(observation)}


def _preview(text: str, limit: int = _PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _digest(messages: Sequence[Message]) -> str:
    payload = json.dumps(
        [[m.role, m.content] for m in messages], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _parse(line: str) -> AuditRecord:
    obj = json.loads(line)
    return AuditRecord(
        ts=str(obj["ts"]), run_id=str(obj["run_id"]), kind=str(obj["kind"]), data=obj["data"]
    )


def _summarize(run_id: str, records: list[AuditRecord]) -> RunSummary:
    finished = next((r for r in reversed(records) if r.kind == "run_finished"), None)
    return RunSummary(
        run_id=run_id,
        started=records[0].ts,
        ended=records[-1].ts,
        events=len(records),
        answer=finished.data.get("answer") if finished else None,
        reason=finished.data.get("reason") if finished else None,
    )
