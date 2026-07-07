"""Labeled prompt set: natural requests, each with the tool it should route to."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    text: str
    expected_tool: str


# Phrasing is deliberately freeform (casual, lowercase, contractions, run-ons) to
# mirror how a user actually talks to an assistant. Each request still maps
# unambiguously to one tool, so the label is fair; the messiness is what stresses
# the model's ability to stay schema-valid without a constrained decoder.
PROMPTS: tuple[Prompt, ...] = (
    Prompt("hey can you dig up any files that mention our q3 budget?", "search_files"),
    Prompt("which of my docs talk about the henderson contract??", "search_files"),
    Prompt("i need to find everything about the vacation policy in my files", "search_files"),
    Prompt("look through my stuff for anything on the api migration pls", "search_files"),
    Prompt("search my files for that 'launch checklist' phrase", "search_files"),
    Prompt("do i have any notes mentioning postgres backups anywhere", "search_files"),
    Prompt("open up notes/roadmap.md and show me what's in it", "read_file"),
    Prompt("what's inside config/settings.yaml? can you read it", "read_file"),
    Prompt("pull up /var/log/app/errors.log for me", "read_file"),
    Prompt("show me the contents of src/deputy/__init__.py", "read_file"),
    Prompt("read README.md real quick", "read_file"),
    Prompt("cat the file at meeting-notes/2026-06-30.txt for me", "read_file"),
    Prompt("jot down that i need to call the dentist tmrw", "add_note"),
    Prompt("make a note: office wifi password is hunter2", "add_note"),
    Prompt("remember for me that sarah likes afternoon meetings", "add_note"),
    Prompt("save a reminder to renew my passport", "add_note"),
    Prompt("note that the client approved the redesign", "add_note"),
    Prompt("take this down — buy oat milk and coffee filters", "add_note"),
    Prompt("what's on my calendar tomorrow?", "get_calendar"),
    Prompt("what do i have going on july 12th", "get_calendar"),
    Prompt("show me my agenda for 2026-07-15", "get_calendar"),
    Prompt("am i free this friday afternoon", "get_calendar"),
    Prompt("list my appointments for next monday", "get_calendar"),
    Prompt("any meetings on the 30th?", "get_calendar"),
)
