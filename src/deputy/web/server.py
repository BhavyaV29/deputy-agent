"""The FastAPI surface: chat, a live action stream, approvals, and the audit log.

    POST /chat                     start a run, returns ``{"run_id": ...}``
    GET  /events/{run_id}          Server-Sent Events for that run
    POST /approvals/{run_id}/{id}  approve or deny a paused tool call
    GET  /api/audit                recent runs and records from the audit log
    GET  /                         the single-page UI

The agent loop is synchronous, so each run executes on a worker thread while its
:class:`~deputy.web.runs.RunSession` streams events and approval prompts back to
the browser. See :mod:`deputy.web.runs` for that bridge.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from threading import Thread
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from deputy.approvals import ApprovalDecision
from deputy.audit import AuditRecord, RunSummary, new_run_id
from deputy.web.runs import RunSession, SessionRegistry, StreamMessage
from deputy.web.service import AgentService

_WEB = Path(__file__).parent
_AUDIT_LIMIT = 200
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class ChatRequest(BaseModel):
    message: str


class ApprovalBody(BaseModel):
    approved: bool
    reason: str = ""


def create_app(service: AgentService) -> FastAPI:
    app = FastAPI(title="Deputy", docs_url=None, redoc_url=None)
    sessions = SessionRegistry()
    index_html = (_WEB / "templates" / "index.html").read_text(encoding="utf-8")
    app.mount("/static", StaticFiles(directory=_WEB / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return index_html

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # A stable marker the launcher probes to tell "Deputy is already running
        # here" apart from "some other process holds this port".
        return {"status": "ok", "app": "deputy"}

    @app.post("/chat")
    async def chat(body: ChatRequest) -> dict[str, str]:
        goal = body.message.strip()
        if not goal:
            raise HTTPException(status_code=422, detail="message must not be empty")
        run_id = new_run_id()
        session = sessions.create(run_id, asyncio.get_running_loop())
        _launch(service, goal, run_id, session)
        return {"run_id": run_id}

    @app.get("/events/{run_id}")
    async def events(run_id: str, request: Request) -> StreamingResponse:
        try:
            session = sessions.get(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown run") from None

        async def publish() -> AsyncIterator[str]:
            try:
                async for message in session.stream():
                    yield _sse(message)
                    if await request.is_disconnected():
                        break
            finally:
                session.cancel_pending()
                sessions.discard(run_id)

        return StreamingResponse(publish(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @app.post("/approvals/{run_id}/{approval_id}")
    async def approve(run_id: str, approval_id: str, body: ApprovalBody) -> dict[str, bool]:
        try:
            reason = body.reason or _reason(body.approved)
            sessions.get(run_id).resolve(approval_id, ApprovalDecision(body.approved, reason))
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown approval") from None
        return {"ok": True}

    @app.get("/api/audit")
    async def audit() -> dict[str, Any]:
        log = service.audit
        return {
            "runs": [_run_summary(s) for s in reversed(log.runs())],
            "records": [_record(r) for r in reversed(log.recent(_AUDIT_LIMIT))],
        }

    return app


def _launch(service: AgentService, goal: str, run_id: str, session: RunSession) -> None:
    def worker() -> None:
        try:
            service.run(goal, run_id=run_id, observer=session.observer, prompter=session.prompter)
        except Exception as exc:  # a failed run becomes a stream message, never a crash
            session.fail(exc)
        finally:
            session.close()

    Thread(target=worker, name=f"deputy-run-{run_id}", daemon=True).start()


def _sse(message: StreamMessage) -> str:
    if message.get("type") == "keepalive":
        return ": keepalive\n\n"
    return f"data: {json.dumps(message, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _reason(approved: bool) -> str:
    return "approved in the browser" if approved else "denied in the browser"


def _record(record: AuditRecord) -> dict[str, Any]:
    return {"ts": record.ts, "run_id": record.run_id, "kind": record.kind, "data": record.data}


def _run_summary(summary: RunSummary) -> dict[str, Any]:
    return {
        "run_id": summary.run_id,
        "started": summary.started,
        "ended": summary.ended,
        "events": summary.events,
        "answer": summary.answer,
        "reason": summary.reason,
    }
