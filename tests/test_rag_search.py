"""Retrieval tool: semantic hits, keyword fallback, and the missing-index path."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from deputy.rag.chunk import Chunk
from deputy.rag.search import DocRetriever, search_docs_tool
from deputy.rag.store import VectorStore


class FakeEmbedder:
    """Maps known queries to fixed vectors; can also simulate being offline."""

    def __init__(
        self, table: Mapping[str, list[float]], dim: int, *, offline: bool = False
    ) -> None:
        self._table = table
        self._dim = dim
        self._offline = offline

    def embed(self, text: str, *, timeout: float | None = None) -> list[float]:
        if self._offline:
            raise RuntimeError("embedder offline")
        return list(self._table.get(text, [0.0] * self._dim))


def _seed(path: Path) -> None:
    with VectorStore.create(path, dim=3, model="fake") as store:
        store.add("cats.md", Chunk(0, "cats purr when content"), [1.0, 0.0, 0.0])
        store.add("space.md", Chunk(0, "rockets reach low orbit"), [0.0, 1.0, 0.0])


def test_semantic_search_returns_sources(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    _seed(db)
    retriever = DocRetriever(db, FakeEmbedder({"felines": [0.95, 0.05, 0.0]}, dim=3), k=1)

    hits = retriever.search("felines")

    assert [hit.path for hit in hits] == ["cats.md"]


def test_falls_back_to_keywords_when_the_embedder_is_offline(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    _seed(db)
    retriever = DocRetriever(db, FakeEmbedder({}, dim=3, offline=True))

    hits = retriever.search("orbit")

    assert [hit.path for hit in hits] == ["space.md"]


def test_tool_formats_hits_with_their_paths(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    _seed(db)
    retriever = DocRetriever(db, FakeEmbedder({"felines": [0.95, 0.05, 0.0]}, dim=3), k=1)
    tool = search_docs_tool(retriever)

    output = tool.handler({"query": "felines"})

    assert "cats.md" in output
    assert "cats purr" in output
    assert tool.mutating is False


def test_tool_guides_the_user_when_no_index_exists(tmp_path: Path) -> None:
    tool = search_docs_tool(DocRetriever(tmp_path / "absent.db", FakeEmbedder({}, dim=3)))
    assert "Build an index" in tool.handler({"query": "anything"})
