"""The sqlite-vec store: nearest-neighbour and keyword queries, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from deputy.rag.chunk import Chunk
from deputy.rag.store import IndexMissingError, VectorStore


def test_vector_search_finds_the_nearest_chunk(tmp_path: Path) -> None:
    with VectorStore.create(tmp_path / "index.db", dim=3, model="fake") as store:
        store.add("cats.md", Chunk(0, "cats purr softly"), [1.0, 0.0, 0.0])
        store.add("space.md", Chunk(0, "rockets reach orbit"), [0.0, 1.0, 0.0])

        nearest = store.vector_search([0.95, 0.05, 0.0], k=1)

    assert [hit.path for hit in nearest] == ["cats.md"]


def test_keyword_search_ranks_by_matched_terms(tmp_path: Path) -> None:
    with VectorStore.create(tmp_path / "index.db", dim=2, model="fake") as store:
        store.add("a.md", Chunk(0, "orbit mechanics and rocket fuel"), [1.0, 0.0])
        store.add("b.md", Chunk(0, "a rocket on the pad"), [0.0, 1.0])

        hits = store.keyword_search("rocket orbit", k=5)

    assert [hit.path for hit in hits] == ["a.md", "b.md"]


def test_keyword_search_with_no_usable_terms_is_empty(tmp_path: Path) -> None:
    with VectorStore.create(tmp_path / "index.db", dim=2, model="fake") as store:
        store.add("a.md", Chunk(0, "content"), [1.0, 0.0])
        assert store.keyword_search("", k=5) == []


def test_rejects_a_wrongly_sized_embedding(tmp_path: Path) -> None:
    with (
        VectorStore.create(tmp_path / "index.db", dim=3, model="fake") as store,
        pytest.raises(ValueError, match="dims"),
    ):
        store.add("a.md", Chunk(0, "text"), [1.0, 2.0])


def test_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    with VectorStore.create(path, dim=2, model="fake") as store:
        store.add("a.md", Chunk(0, "hello world"), [1.0, 1.0])

    with VectorStore.open(path) as reopened:
        assert reopened.count() == 1
        assert reopened.keyword_search("hello", k=3)[0].path == "a.md"


def test_opening_a_missing_index_raises(tmp_path: Path) -> None:
    with pytest.raises(IndexMissingError):
        VectorStore.open(tmp_path / "absent.db")
