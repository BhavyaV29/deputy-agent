"""Build the on-device index: ``python -m deputy.rag.index <dir>``.

Walks a directory for text documents, chunks each one, embeds every chunk through
the configured Ollama model, and writes vectors plus metadata to the sqlite-vec
store. The embedding dimension is taken from the first vector, so the store adapts
to whatever model is configured.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from deputy.config import DeputyConfig
from deputy.model import DEFAULT_HOST, Embedder, OllamaClient
from deputy.rag.chunk import chunk_text
from deputy.rag.store import VectorStore

DEFAULT_EXTENSIONS = (".md", ".markdown", ".txt", ".rst", ".text")


@dataclass(frozen=True)
class IndexStats:
    files: int
    chunks: int


def build_index(
    directory: Path,
    index_path: Path,
    embedder: Embedder,
    *,
    model: str,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
) -> IndexStats:
    records = [
        (relative, chunk)
        for relative, text in _documents(directory, tuple(extensions))
        for chunk in chunk_text(text)
    ]
    if not records:
        raise ValueError(f"no indexable documents under {directory}")

    (first_path, first_chunk), *rest = records
    store = VectorStore.create(index_path, dim=len(embedder.embed(first_chunk.text)), model=model)
    with store:
        store.add(first_path, first_chunk, embedder.embed(first_chunk.text))
        for relative, chunk in rest:
            store.add(relative, chunk, embedder.embed(chunk.text))
    return IndexStats(files=len({path for path, _ in records}), chunks=len(records))


def _documents(directory: Path, extensions: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    root = directory.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            yield str(path.relative_to(root)), path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def main(argv: Sequence[str] | None = None) -> int:
    config = DeputyConfig.from_env()
    parser = argparse.ArgumentParser(prog="deputy.rag.index", description=__doc__)
    parser.add_argument("directory", type=Path, help="directory of documents to index")
    parser.add_argument("--db", type=Path, default=config.index_path, help="index database path")
    parser.add_argument("--model", default=config.embeddings_model, help="Ollama embeddings model")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Ollama base URL")
    args = parser.parse_args(argv)

    try:
        with OllamaClient(model=args.model, host=args.host) as embedder:
            stats = build_index(args.directory, args.db, embedder, model=args.model)
    except httpx.HTTPError as exc:
        print(f"error: could not reach Ollama at {args.host}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"indexed {stats.chunks} chunks from {stats.files} files into {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
