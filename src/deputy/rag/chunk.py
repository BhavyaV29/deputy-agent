"""Split documents into overlapping, embedding-sized chunks.

Splitting follows the document's own structure — paragraphs first, then words for
any paragraph too large to stand alone — so a chunk is a coherent passage rather
than an arbitrary slice. Consecutive chunks share a trailing overlap so a match
that straddles a boundary is still retrievable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_JOIN = "\n\n"


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 150) -> list[Chunk]:
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    window: list[str] = []
    chunks: list[str] = []
    for paragraph in _paragraphs(text, max_chars):
        if window and _length(window + [paragraph]) > max_chars:
            chunks.append(_JOIN.join(window))
            window = _carry(window, overlap)
            if window and _length(window + [paragraph]) > max_chars:
                window = []
        window.append(paragraph)
    if window:
        chunks.append(_JOIN.join(window))
    return [Chunk(ordinal, text) for ordinal, text in enumerate(chunks)]


def _paragraphs(text: str, max_chars: int) -> list[str]:
    blocks: list[str] = []
    for block in _PARAGRAPH_BREAK.split(text.replace("\r\n", "\n").replace("\r", "\n")):
        stripped = block.strip()
        if stripped:
            blocks.extend(_split_oversized(stripped, max_chars))
    return blocks


def _split_oversized(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    pieces: list[str] = []
    current = ""
    for word in block.split():
        if len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
        elif len(f"{current} {word}".strip()) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def _carry(window: list[str], overlap: int) -> list[str]:
    carried: list[str] = []
    for paragraph in reversed(window):
        if _length([paragraph, *carried]) > overlap:
            break
        carried.insert(0, paragraph)
    return carried


def _length(parts: list[str]) -> int:
    return len(_JOIN.join(parts))
