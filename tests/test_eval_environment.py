"""The eval's in-process tool world: deterministic outputs and isolated state."""

from __future__ import annotations

import pytest

from deputy.eval.environment import (
    ADD_NOTE,
    CALCULATOR,
    DELETE_FILE,
    LIST_EVENTS,
    READ_FILE,
    SEARCH_DOCS,
    SEARCH_NOTES,
    SEND_EMAIL,
    WEB_FETCH,
    WebUnavailableError,
    build_registry,
)

ALL_TOOLS = (
    CALCULATOR,
    SEARCH_DOCS,
    READ_FILE,
    LIST_EVENTS,
    SEARCH_NOTES,
    ADD_NOTE,
    SEND_EMAIL,
    DELETE_FILE,
    WEB_FETCH,
)


def test_build_registry_exposes_only_requested_tools() -> None:
    registry, _ = build_registry((CALCULATOR, SEARCH_DOCS))
    assert set(registry.names()) == {CALCULATOR, SEARCH_DOCS}


def test_mutating_flags_match_intent() -> None:
    registry, _ = build_registry(ALL_TOOLS)
    mutating = {tool.name for tool in registry if tool.mutating}
    assert mutating == {ADD_NOTE, SEND_EMAIL, DELETE_FILE}


def test_calculator_evaluates_arithmetic() -> None:
    registry, _ = build_registry((CALCULATOR,))
    assert registry.get(CALCULATOR).handler({"expression": "1234 * 5678"}) == "7006652"


def test_search_docs_is_deterministic_keyword_retrieval() -> None:
    registry, _ = build_registry((SEARCH_DOCS,))
    out = registry.get(SEARCH_DOCS).handler({"query": "vacation days time off"})
    assert "15 vacation days" in out
    assert "handbook/time-off.md" in out


def test_read_file_returns_content_and_reports_missing() -> None:
    registry, _ = build_registry((READ_FILE,))
    assert "max_retries = 5" in registry.get(READ_FILE).handler({"path": "config/limits.txt"})
    with pytest.raises(FileNotFoundError):
        registry.get(READ_FILE).handler({"path": "nope.txt"})


def test_list_events_filters_by_date_and_range() -> None:
    registry, _ = build_registry((LIST_EVENTS,))
    handler = registry.get(LIST_EVENTS).handler
    assert handler({"date_or_range": "2026-07-08"}).count("\n") == 1  # two events, one newline
    assert "Dentist" in handler({"date_or_range": "2026-07-08..2026-07-09"})
    assert "No events" in handler({"date_or_range": "2020-01-01"})


def test_search_notes_reads_seed_and_sandbox_notes() -> None:
    registry, sandbox = build_registry((SEARCH_NOTES, ADD_NOTE))
    assert "oat milk" in registry.get(SEARCH_NOTES).handler({"query": "milk"})
    sandbox.notes.append("remember the umbrella")
    assert "umbrella" in registry.get(SEARCH_NOTES).handler({"query": "umbrella"})


def test_mutating_tools_record_against_the_sandbox() -> None:
    registry, sandbox = build_registry((ADD_NOTE, SEND_EMAIL, DELETE_FILE))
    registry.get(ADD_NOTE).handler({"text": "buy milk"})
    registry.get(SEND_EMAIL).handler({"to": "a@b.com", "body": "hi"})
    registry.get(DELETE_FILE).handler({"path": "x.md"})
    assert sandbox.notes == ["buy milk"]
    assert sandbox.emails == [("a@b.com", "hi")]
    assert sandbox.deleted == ["x.md"]


def test_web_fetch_always_faults() -> None:
    registry, _ = build_registry((WEB_FETCH,))
    with pytest.raises(WebUnavailableError):
        registry.get(WEB_FETCH).handler({"url": "https://example.com"})


def test_each_build_gets_isolated_state() -> None:
    reg_a, box_a = build_registry((ADD_NOTE,))
    _, box_b = build_registry((ADD_NOTE,))
    reg_a.get(ADD_NOTE).handler({"text": "only in a"})
    assert box_a.notes == ["only in a"]
    assert box_b.notes == []
