"""Files server: confinement to the workspace root plus search and read."""

from __future__ import annotations

from pathlib import Path

import pytest

from deputy.servers.files import (
    PathEscapeError,
    read_workspace,
    resolve_within,
    search_workspace,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "notes.md").write_text("Alpha topic lives here.\nsecond line", encoding="utf-8")
    (root / "sub" / "deep.txt").write_text("beta content inside", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("classified", encoding="utf-8")
    return root


def test_reads_a_file_within_the_root(workspace: Path) -> None:
    assert "Alpha topic" in read_workspace(workspace, "notes.md")


@pytest.mark.parametrize("bad", ["../secret.txt", "/etc/hosts", "sub/../../secret.txt"])
def test_rejects_paths_that_escape_the_root(workspace: Path, bad: str) -> None:
    with pytest.raises(PathEscapeError):
        resolve_within(workspace, bad)


def test_rejects_a_symlink_pointing_outside_the_root(workspace: Path) -> None:
    link = workspace / "escape.txt"
    link.symlink_to(workspace.parent / "secret.txt")
    with pytest.raises(PathEscapeError):
        read_workspace(workspace, "escape.txt")


def test_reading_a_missing_file_raises(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_workspace(workspace, "nope.md")


def test_search_matches_file_contents(workspace: Path) -> None:
    result = search_workspace(workspace, "beta")
    assert "sub/deep.txt" in result


def test_search_matches_a_filename(workspace: Path) -> None:
    assert "notes.md" in search_workspace(workspace, "notes")


def test_search_skips_a_symlinked_file_outside_the_root(workspace: Path) -> None:
    (workspace / "escape.txt").symlink_to(workspace.parent / "secret.txt")

    result = search_workspace(workspace, "classified")

    assert result == "No files matched 'classified'."


def test_search_skips_a_symlinked_directory_outside_the_root(workspace: Path) -> None:
    outside = workspace.parent / "outside"
    outside.mkdir()
    (outside / "credentials.txt").write_text("outside-only-token", encoding="utf-8")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    result = search_workspace(workspace, "outside-only-token")

    assert result == "No files matched 'outside-only-token'."


def test_search_reports_no_matches(workspace: Path) -> None:
    assert "No files matched" in search_workspace(workspace, "unfindable-token")


def test_search_rejects_an_empty_query(workspace: Path) -> None:
    assert "non-empty" in search_workspace(workspace, "   ")
