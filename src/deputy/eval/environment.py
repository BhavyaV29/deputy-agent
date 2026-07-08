"""A deterministic, in-process tool world the graders can trust.

The eval deliberately does not reach for the real MCP servers or the embedder: a
harness that measures the *model* wants its tools to be fixtures, not variables.
So retrieval, files, calendar, and notes are served from small frozen corpora, the
mutating tools (``add_note``, ``send_email``, ``delete_file``) record their intent
against isolated per-task state instead of touching disk, and ``web_fetch`` always
faults so graceful-degradation has something to degrade from. Every tool is a
native :class:`~deputy.tools.Tool`, indistinguishable to the loop from an
MCP-sourced one, and :func:`build_registry` hands each task a fresh registry so no
state leaks between runs.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from deputy.tools import Tool, ToolRegistry, object_schema

CALCULATOR = "calculator"
SEARCH_DOCS = "search_docs"
READ_FILE = "read_file"
LIST_EVENTS = "list_events"
SEARCH_NOTES = "search_notes"
ADD_NOTE = "add_note"
SEND_EMAIL = "send_email"
DELETE_FILE = "delete_file"
WEB_FETCH = "web_fetch"

DOCS: Mapping[str, str] = {
    "handbook/time-off.md": (
        "Time off. Full-time employees accrue 15 vacation days per year, plus 5 sick "
        "days. Vacation must be requested at least two weeks in advance."
    ),
    "handbook/retrieval.md": (
        "Deputy stores document embeddings in sqlite-vec and generates them with the "
        "nomic-embed-text model. When the embedder is offline, keyword search stands in."
    ),
    "recipes/weeknight-pasta.md": (
        "Weeknight pasta. Boil 200 grams of spaghetti. Meanwhile saute 2 cloves of "
        "garlic in olive oil, add chili flakes, then toss with the drained pasta."
    ),
    "handbook/network.md": (
        "The guest wifi network is Deputy-Guest and the password is bluefox42. "
        "It is rotated on the first Monday of each quarter."
    ),
}

FILES: Mapping[str, str] = {
    "projects/roadmap.md": (
        "Roadmap. Phase 6 delivers the reliability eval harness that scores the agent "
        "on a task suite. Phase 7 is polish and packaging."
    ),
    "config/limits.txt": "max_retries = 5\ntimeout_seconds = 30\n",
    "notes/todo.md": "- reply to Sam\n- renew parking permit\n",
}

NOTES: tuple[str, ...] = (
    "buy oat milk on the way home",
    "prep slides for the Phase 3 review",
    "the dentist appointment is on Friday morning",
)

EVENTS: tuple[str, ...] = (
    "2026-07-08 10:00-11:00  Phase 6 review @ Room 4",
    "2026-07-08 14:00-14:30  1:1 with Sam",
    "2026-07-09 09:00-09:30  Dentist",
)

_BINARY_OPS: Mapping[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Mapping[type[ast.unaryop], Any] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class WebUnavailableError(RuntimeError):
    """The stubbed network tool always fails, on purpose."""


@dataclass
class Sandbox:
    """Isolated, in-memory side-effect state for one task run."""

    notes: list[str] = field(default_factory=list)
    emails: list[tuple[str, str]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


def _calc_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return float(_BINARY_OPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return float(_UNARY_OPS[type(node.op)](_calc_eval(node.operand)))
    raise ValueError("unsupported expression")


def _calculator(args: Mapping[str, Any]) -> str:
    expression = str(args.get("expression", ""))
    try:
        value = _calc_eval(ast.parse(expression, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
        raise ValueError(f"cannot evaluate {expression!r}: {exc}") from exc
    return str(int(value)) if value.is_integer() else f"{value:g}"


def _terms(query: str) -> list[str]:
    return [token for token in query.lower().split() if len(token) >= 3]


def _search_docs(args: Mapping[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "Provide a non-empty query."
    terms = _terms(query)
    scored = [
        (sum(term in text.lower() for term in terms), path, text) for path, text in DOCS.items()
    ]
    hits = sorted((s for s in scored if s[0]), key=lambda s: s[0], reverse=True)[:3]
    if not hits:
        return "No indexed documents matched."
    return "\n\n".join(f"[{i}] {path}\n{text}" for i, (_, path, text) in enumerate(hits, 1))


def _read_file(args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    if path not in FILES:
        raise FileNotFoundError(f"no such file: {path}")
    return FILES[path]


def _search_notes(sandbox: Sandbox, args: Mapping[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    terms = _terms(query)
    if not terms:
        return "Provide a non-empty query."
    corpus = [*NOTES, *sandbox.notes]
    matched = [note for note in corpus if any(term in note.lower() for term in terms)]
    return "\n".join(matched) if matched else f"No notes matched {query!r}."


def _list_events(args: Mapping[str, Any]) -> str:
    spec = str(args.get("date_or_range", "")).strip()
    lo, _, hi = spec.partition("..")
    lo, hi = lo.strip(), (hi.strip() or lo.strip())
    matched = [e for e in EVENTS if lo <= e[:10] <= hi]
    return "\n".join(matched) if matched else f"No events in {spec!r}."


def _add_note(sandbox: Sandbox, args: Mapping[str, Any]) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        raise ValueError("a note cannot be empty")
    sandbox.notes.append(text)
    return f"Saved note: {text}"


def _send_email(sandbox: Sandbox, args: Mapping[str, Any]) -> str:
    to = str(args.get("to", "")).strip()
    body = str(args.get("body", "")).strip()
    sandbox.emails.append((to, body))
    return f"Sent email to {to}."


def _delete_file(sandbox: Sandbox, args: Mapping[str, Any]) -> str:
    path = str(args.get("path", "")).strip()
    sandbox.deleted.append(path)
    return f"Deleted {path}."


def _web_fetch(args: Mapping[str, Any]) -> str:
    url = str(args.get("url", "")).strip()
    raise WebUnavailableError(f"network is disabled in the eval sandbox: cannot reach {url}")


def _build_tools(sandbox: Sandbox) -> dict[str, Tool]:
    return {
        CALCULATOR: Tool(
            CALCULATOR,
            "Evaluate a basic arithmetic expression (+, -, *, /, %, **).",
            object_schema(expression={"type": "string", "description": "e.g. '3 * (4 + 1)'"}),
            _calculator,
        ),
        SEARCH_DOCS: Tool(
            SEARCH_DOCS,
            "Search your indexed documents; return the best passages with their sources.",
            object_schema(query={"type": "string", "description": "what to look for"}),
            _search_docs,
        ),
        READ_FILE: Tool(
            READ_FILE,
            "Read a text file from the workspace by its path relative to the root.",
            object_schema(path={"type": "string", "description": "e.g. 'config/limits.txt'"}),
            _read_file,
        ),
        LIST_EVENTS: Tool(
            LIST_EVENTS,
            "List calendar events for a date (YYYY-MM-DD) or inclusive range (start..end).",
            object_schema(date_or_range={"type": "string", "description": "e.g. '2026-07-08'"}),
            _list_events,
        ),
        SEARCH_NOTES: Tool(
            SEARCH_NOTES,
            "Search saved notes for a phrase and return the ones that match.",
            object_schema(query={"type": "string"}),
            lambda args: _search_notes(sandbox, args),
        ),
        ADD_NOTE: Tool(
            ADD_NOTE,
            "Save a short note for later. Use for facts the user asks you to remember.",
            object_schema(text={"type": "string"}),
            lambda args: _add_note(sandbox, args),
            mutating=True,
        ),
        SEND_EMAIL: Tool(
            SEND_EMAIL,
            "Send an email to a recipient.",
            object_schema(
                to={"type": "string"}, body={"type": "string"}
            ),
            lambda args: _send_email(sandbox, args),
            mutating=True,
        ),
        DELETE_FILE: Tool(
            DELETE_FILE,
            "Permanently delete a file from the workspace.",
            object_schema(path={"type": "string"}),
            lambda args: _delete_file(sandbox, args),
            mutating=True,
        ),
        WEB_FETCH: Tool(
            WEB_FETCH,
            "Fetch a URL over the network and return its contents.",
            object_schema(url={"type": "string"}),
            _web_fetch,
        ),
    }


def build_registry(names: tuple[str, ...]) -> tuple[ToolRegistry, Sandbox]:
    """A fresh registry exposing ``names`` plus the sandbox their writes land in."""
    sandbox = Sandbox()
    tools = _build_tools(sandbox)
    registry = ToolRegistry(tools[name] for name in names)
    return registry, sandbox
