"""Chunking: structure-aware splitting with overlap and hard limits."""

from __future__ import annotations

import re

import pytest

from deputy.rag.chunk import chunk_text


def test_short_text_is_a_single_chunk() -> None:
    chunks = chunk_text("Just a little text.")
    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert chunks[0].text == "Just a little text."


def test_blank_only_text_yields_nothing() -> None:
    assert chunk_text("   \n\n\t ") == []


def test_every_chunk_respects_the_size_budget() -> None:
    text = "\n\n".join(f"PARA{i} " + "word " * 40 for i in range(8))
    chunks = chunk_text(text, max_chars=300, overlap=60)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 300 for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_carry_a_paragraph_of_overlap() -> None:
    text = "\n\n".join(f"PARA{i}" for i in range(12))
    chunks = chunk_text(text, max_chars=32, overlap=16)
    markers = [set(re.findall(r"PARA\d+", chunk.text)) for chunk in chunks]
    assert len(chunks) > 1
    assert any(markers[i] & markers[i + 1] for i in range(len(markers) - 1))


def test_a_single_oversized_token_is_hard_split() -> None:
    chunks = chunk_text("x" * 1000, max_chars=100, overlap=10)
    assert len(chunks) >= 10
    assert all(len(chunk.text) <= 100 for chunk in chunks)


def test_overlap_must_be_smaller_than_the_budget() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", max_chars=100, overlap=100)
