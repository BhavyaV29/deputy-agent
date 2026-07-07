"""Indexing walks a directory, chunks and embeds it, and fills the store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from deputy.rag.index import build_index
from deputy.rag.store import VectorStore


class HashEmbedder:
    """A deterministic offline embedder: the first bytes of a digest, normalized."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def embed(self, text: str, *, timeout: float | None = None) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[: self._dim]]


def test_indexes_only_text_documents(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "nested").mkdir(parents=True)
    (docs / "a.md").write_text("alpha " * 40, encoding="utf-8")
    (docs / "nested" / "b.txt").write_text("beta content", encoding="utf-8")
    (docs / "image.png").write_bytes(b"\x89PNG\r\n")
    db = tmp_path / "index.db"

    stats = build_index(docs, db, HashEmbedder(), model="fake")

    assert stats.files == 2
    assert stats.chunks >= 2
    with VectorStore.open(db) as store:
        assert store.count() == stats.chunks


def test_a_directory_with_no_documents_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no indexable documents"):
        build_index(tmp_path, tmp_path / "index.db", HashEmbedder(), model="fake")
