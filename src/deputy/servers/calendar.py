"""Read-only calendar lookups over a local JSON store.

The store is a JSON array of events; a query is either a single ISO date
(``2026-07-08``) or an inclusive range (``2026-07-08..2026-07-10``). Keeping the
source local and read-only means calendar access never reaches the network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

CALENDAR_PATH_ENV = "DEPUTY_CALENDAR_PATH"


@dataclass(frozen=True)
class Event:
    date: str
    start: str
    end: str
    title: str
    location: str = ""


def list_events(path: Path, date_or_range: str) -> str:
    start, end = _parse_range(date_or_range)
    events = sorted(
        (e for e in _load(path) if start <= date.fromisoformat(e.date) <= end),
        key=lambda e: (e.date, e.start),
    )
    if not events:
        return f"No events between {start} and {end}."
    return "\n".join(_format(event) for event in events)


def _format(event: Event) -> str:
    where = f" @ {event.location}" if event.location else ""
    return f"{event.date} {event.start}-{event.end}  {event.title}{where}"


def _parse_range(spec: str) -> tuple[date, date]:
    spec = spec.strip()
    if ".." in spec:
        lo, hi = (part.strip() for part in spec.split("..", 1))
        return date.fromisoformat(lo), date.fromisoformat(hi)
    day = date.fromisoformat(spec)
    return day, day


def _load(path: Path) -> list[Event]:
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    return [
        Event(
            date=str(r["date"]),
            start=str(r.get("start", "")),
            end=str(r.get("end", "")),
            title=str(r["title"]),
            location=str(r.get("location", "")),
        )
        for r in records
    ]


def _path() -> Path:
    return Path(os.environ.get(CALENDAR_PATH_ENV, "data/calendar.json")).expanduser().resolve()


mcp = FastMCP("calendar")


@mcp.tool(
    name="list_events",
    description=(
        "List calendar events for a date (YYYY-MM-DD) or inclusive range (YYYY-MM-DD..YYYY-MM-DD)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
def list_events_tool(date_or_range: str) -> str:
    return list_events(_path(), date_or_range)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
