"""On-device retrieval: chunk documents, embed them, search them locally.

Embeddings go through the injected :class:`~deputy.model.Embedder`, so indexing
and retrieval are exercised in tests with a deterministic fake and never require
Ollama. Vectors and chunk metadata live in a local sqlite-vec database under the
data directory.
"""

from __future__ import annotations

from deputy.rag.chunk import Chunk, chunk_text
from deputy.rag.search import DocHit, DocRetriever, search_docs_tool
from deputy.rag.store import Retrieved, VectorStore

__all__ = [
    "Chunk",
    "DocHit",
    "DocRetriever",
    "Retrieved",
    "VectorStore",
    "chunk_text",
    "search_docs_tool",
]
