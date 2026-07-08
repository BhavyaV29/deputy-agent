"""The web layer: chat runs, SSE streaming, the approval gate, and the audit view.

Each test serves the app from a real uvicorn instance on an ephemeral loopback
port, so the SSE stream and the approve/deny request run on independent
connections — the concurrency the browser actually relies on. Runs go through the
real approval and audit seams, driven by a scripted fake model, so nothing here
needs a live Ollama.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from deputy.actions import ToolCall
from deputy.agent import Agent, AgentResult
from deputy.approvals import ApprovalDecision, Prompter, policy_approver, recording_approver
from deputy.audit import AuditLog
from deputy.events import ActionPlanned, EventSink, RunFinished, StopReason, ToolObserved, fanout
from deputy.model import ChatResponse, Message
from deputy.tools import Tool, ToolRegistry, object_schema
from deputy.web.launcher import probe_deputy, resolve_endpoint
from deputy.web.server import create_app

_TIMEOUT = 10.0


class ScriptedModel:
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


def _reader(args: Mapping[str, Any]) -> str:
    return f"found: {args.get('q', '')}"


def make_registry(writes: list[str]) -> ToolRegistry:
    def writer(args: Mapping[str, Any]) -> str:
        writes.append(str(args["text"]))
        return f"saved: {args['text']}"

    return ToolRegistry(
        [
            Tool("search", "look things up", object_schema(q={"type": "string"}), _reader),
            Tool("add_note", "save a note", object_schema(text={"type": "string"}), writer, True),
        ]
    )


class FakeService:
    """An :class:`AgentService` backed by a scripted model and the real seams."""

    def __init__(
        self,
        audit: AuditLog,
        replies: Sequence[str],
        registry: Callable[[], ToolRegistry],
    ) -> None:
        self._audit = audit
        self._replies = list(replies)
        self._registry = registry

    @property
    def audit(self) -> AuditLog:
        return self._audit

    def run(
        self, goal: str, *, run_id: str, observer: EventSink, prompter: Prompter
    ) -> AgentResult:
        registry = self._registry()
        recorder = self._audit.run(run_id)
        approve = recording_approver(policy_approver(registry, prompter), recorder.record_approval)
        agent = Agent(
            ScriptedModel(self._replies),
            registry,
            approve=approve,
            on_event=fanout(recorder, observer),
        )
        return agent.run(goal)


def _service(tmp_path: Path, replies: Sequence[str], writes: list[str]) -> FakeService:
    return FakeService(AuditLog(tmp_path / "audit.jsonl"), replies, lambda: make_registry(writes))


def _tool(name: str, **args: Any) -> str:
    return json.dumps({"tool": name, "args": args})


def _final(text: str) -> str:
    return json.dumps({"final": text})


@contextlib.contextmanager
def _serve(service: FakeService) -> Iterator[httpx.Client]:
    config = uvicorn.Config(
        create_app(service), host="127.0.0.1", port=0, log_level="warning", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _TIMEOUT
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=_TIMEOUT) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=_TIMEOUT)


def _start(client: httpx.Client, message: str) -> str:
    return str(client.post("/chat", json={"message": message}).json()["run_id"])


def _stream(client: httpx.Client, run_id: str, *, approve: bool | None = None) -> list[Any]:
    seen: list[Any] = []
    with client.stream("GET", f"/events/{run_id}") as response:
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[len("data:") :].strip())
            seen.append(event)
            if event["type"] == "approval_request" and approve is not None:
                reply = client.post(
                    f"/approvals/{run_id}/{event['approval_id']}", json={"approved": approve}
                )
                assert reply.status_code == 200
    return seen


def test_index_page_and_static_assets_are_served(tmp_path: Path) -> None:
    with _serve(_service(tmp_path, [_final("hi")], [])) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Deputy" in page.text
        # The one-click sample tasks are server-rendered so the demo flow (and
        # its gif) stays a single click, and the mutating one is present.
        assert "Try a sample task" in page.text
        assert "Save a note:" in page.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200


def test_healthz_lets_the_launcher_detect_a_running_deputy(tmp_path: Path) -> None:
    with _serve(_service(tmp_path, [_final("x")], [])) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "app": "deputy"}

        port = client.base_url.port
        assert port is not None
        # The launcher must recognise this instance and reuse its port rather
        # than trying to bind a second server there.
        assert probe_deputy("127.0.0.1", port) is True
        endpoint = resolve_endpoint("127.0.0.1", port)
        assert endpoint.port == port
        assert endpoint.already_running is True


def test_chat_run_streams_plan_observation_and_answer(tmp_path: Path) -> None:
    service = _service(tmp_path, [_tool("search", q="cats"), _final("all done")], [])
    with _serve(service) as client:
        messages = _stream(client, _start(client, "look up cats"))

    assert [m["type"] for m in messages] == [
        "action_planned",
        "tool_observed",
        "action_planned",
        "run_finished",
    ]
    observed = next(m for m in messages if m["type"] == "tool_observed")
    assert observed["tool"] == "search"
    assert observed["ok"] is True
    assert messages[-1]["answer"] == "all done"
    assert messages[-1]["reason"] == "answered"


def test_approval_gate_runs_the_write_when_approved(tmp_path: Path) -> None:
    writes: list[str] = []
    service = _service(tmp_path, [_tool("add_note", text="buy milk"), _final("saved it")], writes)
    with _serve(service) as client:
        run_id = _start(client, "note buy milk")
        messages = _stream(client, run_id, approve=True)

    assert writes == ["buy milk"]
    request = next(m for m in messages if m["type"] == "approval_request")
    assert request["tool"] == "add_note"
    assert request["mutating"] is True
    observed = next(m for m in messages if m["type"] == "tool_observed")
    assert observed["tool"] == "add_note"
    assert observed["ok"] is True
    assert messages[-1]["answer"] == "saved it"

    approvals = [r for r in service.audit.by_run(run_id) if r.kind == "approval"]
    assert approvals and approvals[0].data["approved"] is True


def test_approval_gate_skips_the_write_when_denied(tmp_path: Path) -> None:
    writes: list[str] = []
    service = _service(tmp_path, [_tool("add_note", text="secret"), _final("ok, skipped")], writes)
    with _serve(service) as client:
        run_id = _start(client, "note secret")
        messages = _stream(client, run_id, approve=False)

    assert writes == []
    denied = next(m for m in messages if m["type"] == "action_denied")
    assert denied["tool"] == "add_note"
    assert messages[-1]["answer"] == "ok, skipped"

    approvals = [r for r in service.audit.by_run(run_id) if r.kind == "approval"]
    assert approvals and approvals[0].data["approved"] is False


def test_empty_message_is_rejected(tmp_path: Path) -> None:
    with _serve(_service(tmp_path, [_final("x")], [])) as client:
        assert client.post("/chat", json={"message": "   "}).status_code == 422


def test_unknown_run_and_approval_return_404(tmp_path: Path) -> None:
    with _serve(_service(tmp_path, [_final("x")], [])) as client:
        assert client.get("/events/missing").status_code == 404
        assert client.post("/approvals/missing/abc", json={"approved": True}).status_code == 404


def test_audit_view_returns_runs_and_records(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    recorder = audit.run("run-1")
    call = ToolCall("add_note", {"text": "hi"})
    recorder(ActionPlanned(1, call))
    recorder(ToolObserved(1, call, "saved", ok=True))
    recorder.record_approval(call, ApprovalDecision(True, "approved in the browser"))
    recorder(RunFinished(2, "done", StopReason.ANSWERED))
    service = FakeService(audit, [_final("unused")], lambda: make_registry([]))

    with _serve(service) as client:
        data = client.get("/api/audit").json()

    assert [run["run_id"] for run in data["runs"]] == ["run-1"]
    summary = data["runs"][0]
    assert summary["reason"] == "answered"
    assert summary["answer"] == "done"
    kinds = [record["kind"] for record in data["records"]]
    assert "approval" in kinds
    assert "run_finished" in kinds
