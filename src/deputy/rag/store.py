"""A local vector store backed by sqlite-vec.

Chunk text and its metadata live in an ordinary table; the embeddings live in a
sibling ``vec0`` virtual table keyed by the same rowid, so a nearest-neighbour
query is a join. The store also answers keyword queries straight from the text
column, which is the fallback used when no embedder is available.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

import sqlite_vec

from deputy.rag.chunk import Chunk

_MIN_TERM_LEN = 3


class IndexMissingError(FileNotFoundError):
    """No index database exists at the requested path yet."""


@dataclass(frozen=True)
class Retrieved:
    path: str
    ordinal: int
    text: str


class VectorStore:
    def __init__(self, connection: sqlite3.Connection, dim: int) -> None:
        self._db = connection
        self._dim = dim

    @classmethod
    def create(cls, path: Path, *, dim: int, model: str) -> Self:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = _connect(path)
        db.executescript(
            "DROP TABLE IF EXISTS chunks;"
            "DROP TABLE IF EXISTS vec_chunks;"
            "DROP TABLE IF EXISTS meta;"
            "CREATE TABLE chunks(id INTEGER PRIMARY KEY, path TEXT NOT NULL,"
            " ordinal INTEGER NOT NULL, text TEXT NOT NULL);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        db.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])")
        db.executemany("INSERT INTO meta VALUES(?, ?)", [("dim", str(dim)), ("model", model)])
        db.commit()
        return cls(db, dim)

    @classmethod
    def open(cls, path: Path) -> Self:
        if not path.exists():
            raise IndexMissingError(str(path))
        db = _connect(path)
        row = db.execute("SELECT value FROM meta WHERE key = 'dim'").fetchone()
        if row is None:
            raise IndexMissingError(str(path))
        return cls(db, int(row[0]))

    def add(self, path: str, chunk: Chunk, embedding: Sequence[float]) -> None:
        if len(embedding) != self._dim:
            raise ValueError(f"embedding has {len(embedding)} dims, store expects {self._dim}")
        cursor = self._db.execute(
            "INSERT INTO chunks(path, ordinal, text) VALUES(?, ?, ?)",
            (path, chunk.ordinal, chunk.text),
        )
        self._db.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES(?, ?)",
            (cursor.lastrowid, sqlite_vec.serialize_float32(list(embedding))),
        )
        self._db.commit()

    def vector_search(self, embedding: Sequence[float], k: int) -> list[Retrieved]:
        rows = self._db.execute(
            "SELECT c.path, c.ordinal, c.text FROM vec_chunks v JOIN chunks c ON c.id = v.rowid"
            " WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (sqlite_vec.serialize_float32(list(embedding)), k),
        ).fetchall()
        return [Retrieved(*row) for row in rows]

    def keyword_search(self, query: str, k: int) -> list[Retrieved]:
        terms = _terms(query)
        if not terms:
            return []
        likes = [f"%{term}%" for term in terms]
        score = " + ".join(["(lower(text) LIKE ?)"] * len(terms))
        where = " OR ".join(["lower(text) LIKE ?"] * len(terms))
        rows = self._db.execute(
            f"SELECT path, ordinal, text FROM chunks WHERE {where}"
            f" ORDER BY ({score}) DESC, id LIMIT ?",
            (*likes, *likes, k),
        ).fetchall()
        return [Retrieved(*row) for row in rows]

    def count(self) -> int:
        return int(self._db.execute("SELECT count(*) FROM chunks").fetchone()[0])

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def _terms(query: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    return [t for t in tokens if len(t) >= _MIN_TERM_LEN] or tokens
