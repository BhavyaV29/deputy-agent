"""A tiny append-only note store kept as JSON Lines under the data directory.

``add_note`` is Deputy's first genuinely mutating tool. It is annotated as a write
so the host tags it ``mutating`` and Phase 4 can require approval for it, while the
lookup stays read-only.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

NOTES_PATH_ENV = "DEPUTY_NOTES_PATH"
_MIN_TERM_LEN = 3


@dataclass(frozen=True)
class Note:
    created: str
    text: str


def add_note(path: Path, text: str) -> Note:
    body = text.strip()
    if not body:
        raise ValueError("a note cannot be empty")
    note = Note(created=datetime.now(UTC).isoformat(timespec="seconds"), text=body)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"created": note.created, "text": note.text}) + "\n")
    return note


def search_notes(path: Path, query: str) -> str:
    # Keyword rather than whole-string matching: the caller (often a model) tends
    # to pass a verbose query, and a note is relevant if it shares any of its terms.
    terms = _terms(query)
    if not terms:
        return "Provide a non-empty query."
    scored = [(sum(term in note.text.lower() for term in terms), note) for note in _load(path)]
    matched = sorted((s for s in scored if s[0]), key=lambda s: s[0], reverse=True)
    if not matched:
        return f"No notes matched {query!r}."
    return "\n".join(f"[{note.created}] {note.text}" for _, note in matched)


def _load(path: Path) -> Iterator[Note]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            record = json.loads(line)
            yield Note(created=str(record["created"]), text=str(record["text"]))


def _terms(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [token for token in tokens if len(token) >= _MIN_TERM_LEN] or tokens


def _path() -> Path:
    return Path(os.environ.get(NOTES_PATH_ENV, "data/notes.jsonl")).expanduser().resolve()


mcp = FastMCP("notes")


@mcp.tool(
    name="add_note",
    description="Save a short note for later. Use for facts the user asks you to remember.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
)
def add_note_tool(text: str) -> str:
    note = add_note(_path(), text)
    return f"Saved note at {note.created}."


@mcp.tool(
    name="search_notes",
    description="Search saved notes for a phrase and return the ones that match.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def search_notes_tool(query: str) -> str:
    return search_notes(_path(), query)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
