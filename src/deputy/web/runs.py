"""Bridge the synchronous agent loop to the browser over Server-Sent Events.

The loop is blocking: it reports progress through a synchronous
:data:`~deputy.events.EventSink` and asks permission through a synchronous
:data:`~deputy.approvals.Prompter`. The browser speaks async HTTP. Each run
therefore executes on a worker thread while a :class:`RunSession` marshals its
output back onto the event loop — events and approval prompts are handed to an
:class:`asyncio.Queue` via ``call_soon_threadsafe``, and an approval parks the
worker on a :class:`concurrent.futures.Future` that the approve/deny endpoint
completes from the loop. The loop stays untouched: the UI is simply another
implementation of the existing prompter seam.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import Future
from typing import Any

from deputy.actions import Action, FinalAnswer
from deputy.approvals import ApprovalDecision, ApprovalRequest, Prompter
from deputy.events import (
    ActionDenied,
    ActionPlanned,
    AnswerRejected,
    Event,
    EventSink,
    RunFinished,
    ToolObserved,
)

StreamMessage = dict[str, Any]

_HEARTBEAT_SECONDS = 15.0


class RunSession:
    """One in-flight run: a stream of messages plus its pending approvals.

    The ``observer``/``prompter`` are called from the worker thread; ``resolve``
    and ``stream`` are driven from the event loop. The two sides meet only at the
    thread-safe queue and futures, so neither blocks the other.
    """

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.run_id = run_id
        self._loop = loop
        self._queue: asyncio.Queue[StreamMessage | None] = asyncio.Queue()
        self._pending: dict[str, Future[ApprovalDecision]] = {}

    @property
    def observer(self) -> EventSink:
        return self._on_event

    @property
    def prompter(self) -> Prompter:
        return self._prompt

    def close(self) -> None:
        """Mark end-of-stream once the worker returns, however it returned."""
        self._emit(None)

    def fail(self, error: BaseException) -> None:
        self._emit({"type": "error", "message": f"{type(error).__name__}: {error}"})

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> None:
        """Answer a pending approval from the loop; wakes the worker thread."""
        self._pending.pop(approval_id).set_result(decision)

    def cancel_pending(self) -> None:
        """Deny anything still waiting so an abandoned run's worker can exit."""
        while self._pending:
            _, future = self._pending.popitem()
            if not future.done():
                future.set_result(ApprovalDecision(False, "run cancelled"))

    async def stream(self) -> AsyncIterator[StreamMessage]:
        while True:
            try:
                message = await asyncio.wait_for(self._queue.get(), _HEARTBEAT_SECONDS)
            except TimeoutError:
                yield {"type": "keepalive"}
                continue
            if message is None:
                return
            yield message

    def _on_event(self, event: Event) -> None:
        self._emit(_event_message(event))

    def _prompt(self, request: ApprovalRequest) -> ApprovalDecision:
        approval_id = uuid.uuid4().hex[:12]
        decision: Future[ApprovalDecision] = Future()
        self._pending[approval_id] = decision
        self._emit(_approval_message(approval_id, request))
        return decision.result()

    def _emit(self, message: StreamMessage | None) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, message)


class SessionRegistry:
    """The live sessions, keyed by run id. Lookups miss with :class:`KeyError`."""

    def __init__(self) -> None:
        self._sessions: dict[str, RunSession] = {}

    def create(self, run_id: str, loop: asyncio.AbstractEventLoop) -> RunSession:
        session = RunSession(run_id, loop)
        self._sessions[run_id] = session
        return session

    def get(self, run_id: str) -> RunSession:
        return self._sessions[run_id]

    def discard(self, run_id: str) -> None:
        self._sessions.pop(run_id, None)


def _event_message(event: Event) -> StreamMessage:
    match event:
        case ActionPlanned(step, action):
            return {"type": "action_planned", "step": step, "action": _action(action)}
        case ToolObserved(step, call, observation, ok):
            return {
                "type": "tool_observed",
                "step": step,
                "tool": call.tool,
                "args": dict(call.args),
                "observation": observation,
                "ok": ok,
            }
        case ActionDenied(step, call, reason):
            return {
                "type": "action_denied",
                "step": step,
                "tool": call.tool,
                "args": dict(call.args),
                "reason": reason,
            }
        case AnswerRejected(step, answer, feedback):
            return {"type": "answer_rejected", "step": step, "answer": answer, "feedback": feedback}
        case RunFinished(step, answer, reason):
            return {"type": "run_finished", "step": step, "answer": answer, "reason": str(reason)}


def _action(action: Action) -> StreamMessage:
    if isinstance(action, FinalAnswer):
        return {"kind": "final", "text": action.text}
    return {"kind": "tool", "tool": action.tool, "args": dict(action.args)}


def _approval_message(approval_id: str, request: ApprovalRequest) -> StreamMessage:
    return {
        "type": "approval_request",
        "approval_id": approval_id,
        "tool": request.call.tool,
        "args": dict(request.call.args),
        "description": request.description,
        "mutating": request.mutating,
        "risk": request.risk,
        "reason": request.reason,
    }
