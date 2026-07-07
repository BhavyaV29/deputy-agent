"""Dataset-integrity checks for the labeled prompt set."""

from __future__ import annotations

from collections import Counter

from deputy.spike.prompts import PROMPTS
from deputy.spike.tools import TOOLS_BY_NAME


def test_has_at_least_twenty_four_prompts() -> None:
    assert len(PROMPTS) >= 24


def test_every_expected_tool_exists() -> None:
    for prompt in PROMPTS:
        assert prompt.expected_tool in TOOLS_BY_NAME


def test_every_tool_is_exercised() -> None:
    covered = {prompt.expected_tool for prompt in PROMPTS}
    assert covered == set(TOOLS_BY_NAME)


def test_prompt_text_is_unique() -> None:
    counts = Counter(prompt.text for prompt in PROMPTS)
    assert all(count == 1 for count in counts.values())
