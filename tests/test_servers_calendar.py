"""Calendar server: date and range lookups over a local JSON store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deputy.servers.calendar import list_events


@pytest.fixture
def calendar(tmp_path: Path) -> Path:
    store = tmp_path / "calendar.json"
    store.write_text(
        json.dumps(
            [
                {"date": "2026-07-08", "start": "09:30", "end": "10:00", "title": "Review"},
                {"date": "2026-07-08", "start": "13:00", "end": "13:30", "title": "Lunch"},
                {"date": "2026-07-09", "start": "11:00", "end": "12:00", "title": "Dentist"},
            ]
        ),
        encoding="utf-8",
    )
    return store


def test_lists_events_for_a_single_date(calendar: Path) -> None:
    result = list_events(calendar, "2026-07-08")
    assert "Review" in result and "Lunch" in result
    assert "Dentist" not in result


def test_lists_events_across_an_inclusive_range(calendar: Path) -> None:
    result = list_events(calendar, "2026-07-08..2026-07-09")
    assert "Review" in result and "Dentist" in result


def test_events_are_ordered_by_time(calendar: Path) -> None:
    result = list_events(calendar, "2026-07-08")
    assert result.index("Review") < result.index("Lunch")


def test_reports_an_empty_day(calendar: Path) -> None:
    assert "No events" in list_events(calendar, "2026-07-10")


def test_a_missing_store_has_no_events(tmp_path: Path) -> None:
    assert "No events" in list_events(tmp_path / "absent.json", "2026-07-08")


def test_an_invalid_date_is_rejected(calendar: Path) -> None:
    with pytest.raises(ValueError):
        list_events(calendar, "not-a-date")
