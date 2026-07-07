"""Notes server: append a note, then find it again."""

from __future__ import annotations

from pathlib import Path

import pytest

from deputy.servers.notes import add_note, search_notes


def test_added_notes_are_searchable(tmp_path: Path) -> None:
    store = tmp_path / "notes.jsonl"
    add_note(store, "buy oat milk on the way home")
    add_note(store, "phase 3 review is on Wednesday")

    assert "oat milk" in search_notes(store, "milk")
    assert "phase 3 review" in search_notes(store, "review")


def test_search_reports_no_matches(tmp_path: Path) -> None:
    store = tmp_path / "notes.jsonl"
    add_note(store, "something unrelated")
    assert "No notes matched" in search_notes(store, "taxes")


def test_search_matches_on_shared_terms_not_the_whole_query(tmp_path: Path) -> None:
    store = tmp_path / "notes.jsonl"
    add_note(store, "Prep slides for the Phase 3 review")
    # A verbose query still matches on the overlapping "phase"/"review" terms.
    result = search_notes(store, "Phase 3 review @ home office, then lunch")
    assert "Prep slides" in result


def test_searching_a_missing_store_is_empty_not_an_error(tmp_path: Path) -> None:
    assert "No notes matched" in search_notes(tmp_path / "absent.jsonl", "anything")


def test_an_empty_note_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        add_note(tmp_path / "notes.jsonl", "   ")


def test_note_records_a_timestamp(tmp_path: Path) -> None:
    note = add_note(tmp_path / "notes.jsonl", "remember this")
    assert note.text == "remember this"
    assert note.created  # ISO-8601 timestamp
