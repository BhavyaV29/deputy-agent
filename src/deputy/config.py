"""Runtime configuration, resolved from the environment with local defaults.

Everything Deputy reads or writes at runtime lives under a single ``data`` dir so
it can be gitignored wholesale and nothing about a user's machine leaks into the
repo. Paths are resolved to absolutes here because the built-in tool servers run
as separate subprocesses with their own working directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

_TRUTHY = frozenset({"1", "true", "yes", "on"})

DEFAULT_EMBEDDINGS_MODEL = "nomic-embed-text"


@dataclass(frozen=True)
class DeputyConfig:
    data_dir: Path
    workspace_root: Path
    notes_path: Path
    calendar_path: Path
    index_path: Path
    embeddings_model: str
    web_search_enabled: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, base: Path | None = None) -> Self:
        env = os.environ if env is None else env
        root = (base or Path.cwd()).resolve()
        data_dir = _path(env, "DEPUTY_DATA_DIR", root / "data")
        return cls(
            data_dir=data_dir,
            workspace_root=_path(env, "DEPUTY_WORKSPACE_ROOT", root / "sample_workspace"),
            notes_path=_path(env, "DEPUTY_NOTES_PATH", data_dir / "notes.jsonl"),
            calendar_path=_path(env, "DEPUTY_CALENDAR_PATH", data_dir / "calendar.json"),
            index_path=_path(env, "DEPUTY_INDEX_PATH", data_dir / "index.db"),
            embeddings_model=env.get("DEPUTY_EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL),
            web_search_enabled=env.get("DEPUTY_WEB_SEARCH_ENABLED", "").strip().lower() in _TRUTHY,
        )

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _path(env: Mapping[str, str], key: str, default: Path) -> Path:
    value = env.get(key)
    return Path(value).expanduser().resolve() if value else default
