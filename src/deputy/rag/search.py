"""Retrieval over the local index, exposed to the agent as ``search_docs``.

Retrieval prefers semantic (vector) matches and silently falls back to keyword
matches when the embedder is unavailable or returns nothing, so the tool degrades
gracefully instead of failing the loop. Every hit carries its source path, which
lets the agent cite where an answer came from and open the file for more.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deputy.model import Embedder
from deputy.rag.store import IndexMissingError, Retrieved, VectorStore
from deputy.tools import Tool, object_schema

_SNIPPET_CHARS = 480


@dataclass(frozen=True)
class DocHit:
    path: str
    text: str


class DocRetriever:
    def __init__(self, index_path: Path, embedder: Embedder, *, k: int = 4) -> None:
        self._index_path = index_path
        self._embedder = embedder
        self._k = k

    def search(self, query: str) -> list[DocHit]:
        try:
            store = VectorStore.open(self._index_path)
        except IndexMissingError:
            return []
        with store:
            hits = self._semantic(store, query) or store.keyword_search(query, self._k)
        return [DocHit(hit.path, hit.text) for hit in hits]

    def _semantic(self, store: VectorStore, query: str) -> list[Retrieved]:
        try:
            embedding = self._embedder.embed(query)
        except Exception:  # embedder offline — let the caller fall back to keywords
            return []
        return store.vector_search(embedding, self._k)


def search_docs_tool(retriever: DocRetriever) -> Tool:
    def handler(args: Mapping[str, Any]) -> str:
        query = str(args["query"]).strip()
        if not query:
            return "Provide a non-empty query."
        hits = retriever.search(query)
        if not hits:
            return (
                "No indexed documents matched. "
                "Build an index with `python -m deputy.rag.index <dir>`."
            )
        return "\n\n".join(
            f"[{i}] {hit.path}\n{_snippet(hit.text)}" for i, hit in enumerate(hits, 1)
        )

    return Tool(
        name="search_docs",
        description="Search your indexed documents; return the best passages with their sources.",
        parameters=object_schema(query={"type": "string", "description": "what to look for"}),
        handler=handler,
    )


def _snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_CHARS] + "..."
