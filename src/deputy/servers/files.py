"""Read-only access to a single configured workspace directory.

Confinement is the whole point of this server: every path the caller supplies is
resolved and checked to fall under the workspace root before anything is read, so
``..`` traversal, absolute paths, and symlinks that point outside the tree are all
rejected rather than served.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

WORKSPACE_ROOT_ENV = "DEPUTY_WORKSPACE_ROOT"
_MAX_FILE_BYTES = 1_000_000
_MAX_READ_CHARS = 10_000
_MAX_MATCHES = 20


class PathEscapeError(ValueError):
    """A requested path resolved outside the workspace root."""


def resolve_within(root: Path, candidate: str) -> Path:
    root = root.resolve()
    target = (root / candidate).resolve()
    if target == root or root in target.parents:
        return target
    raise PathEscapeError(f"path {candidate!r} escapes the workspace")


def search_workspace(root: Path, query: str) -> str:
    needle = query.strip().lower()
    if not needle:
        return "Provide a non-empty query."

    matches: list[str] = []
    for rel, text in _text_files(root.resolve()):
        if needle in rel.lower():
            matches.append(f"{rel} (filename)")
        line = _first_match(text, needle)
        if line is not None:
            matches.append(f"{rel}: {line}")
        if len(matches) >= _MAX_MATCHES:
            break

    if not matches:
        return f"No files matched {query!r}."
    return "\n".join(matches)


def read_workspace(root: Path, path: str) -> str:
    target = resolve_within(root, path)
    if not target.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_READ_CHARS:
        return text[:_MAX_READ_CHARS] + "\n... (truncated)"
    return text


def _text_files(root: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_hidden(path, root):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or binary — skip rather than fail the search
        files.append((str(path.relative_to(root)), text))
    return files


def _is_hidden(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _first_match(text: str, needle: str) -> str | None:
    for raw in text.splitlines():
        if needle in raw.lower():
            line = raw.strip()
            return line if len(line) <= 200 else line[:200] + "..."
    return None


def _root() -> Path:
    return Path(os.environ.get(WORKSPACE_ROOT_ENV, ".")).expanduser().resolve()


mcp = FastMCP("files")


@mcp.tool(
    name="search_files",
    description="Search the workspace for files whose name or contents mention a phrase.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def search_files(query: str) -> str:
    return search_workspace(_root(), query)


@mcp.tool(
    name="read_file",
    description="Read a text file from the workspace by its path relative to the root.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def read_file(path: str) -> str:
    return read_workspace(_root(), path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
