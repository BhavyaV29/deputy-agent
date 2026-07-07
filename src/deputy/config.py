"""Runtime configuration, resolved from the environment with local defaults.

Everything Deputy reads or writes at runtime lives under a single ``data`` dir so
it can be gitignored wholesale and nothing about a user's machine leaks into the
repo. Paths are resolved to absolutes here because the built-in tool servers run
as separate subprocesses with their own working directory. The Phase-4 settings
follow the same rule: local-first, with cloud escalation off unless explicitly
switched on *and* given a key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from deputy.approvals import TrustLevel
from deputy.audit import DEFAULT_REDACT

_TRUTHY = frozenset({"1", "true", "yes", "on"})

DEFAULT_EMBEDDINGS_MODEL = "nomic-embed-text"
DEFAULT_CLOUD_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CLOUD_MODEL = "gpt-4o-mini"
DEFAULT_ESCALATE_CHARS = 6000


@dataclass(frozen=True)
class DeputyConfig:
    data_dir: Path
    workspace_root: Path
    notes_path: Path
    calendar_path: Path
    index_path: Path
    audit_path: Path
    audit_redact: frozenset[str]
    trust_overrides: Mapping[str, TrustLevel]
    embeddings_model: str
    web_search_enabled: bool
    cloud_enabled: bool
    cloud_base_url: str
    cloud_model: str
    cloud_api_key: str | None
    cloud_escalate_chars: int

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
            audit_path=_path(env, "DEPUTY_AUDIT_PATH", data_dir / "audit.jsonl"),
            audit_redact=_redact(env.get("DEPUTY_AUDIT_REDACT")),
            trust_overrides=_trust(env.get("DEPUTY_TRUST")),
            embeddings_model=env.get("DEPUTY_EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL),
            web_search_enabled=_flag(env, "DEPUTY_WEB_SEARCH_ENABLED"),
            cloud_enabled=_flag(env, "DEPUTY_CLOUD_ENABLED"),
            cloud_base_url=env.get("DEPUTY_CLOUD_BASE_URL", DEFAULT_CLOUD_BASE_URL),
            cloud_model=env.get("DEPUTY_CLOUD_MODEL", DEFAULT_CLOUD_MODEL),
            cloud_api_key=env.get("DEPUTY_CLOUD_API_KEY") or None,
            cloud_escalate_chars=_int(env, "DEPUTY_CLOUD_ESCALATE_CHARS", DEFAULT_ESCALATE_CHARS),
        )

    @property
    def cloud_ready(self) -> bool:
        """Cloud escalation may run only when opted in *and* holding a key."""
        return self.cloud_enabled and bool(self.cloud_api_key)

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _path(env: Mapping[str, str], key: str, default: Path) -> Path:
    value = env.get(key)
    return Path(value).expanduser().resolve() if value else default


def _flag(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in _TRUTHY


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    return int(value) if value else default


def _redact(raw: str | None) -> frozenset[str]:
    if raw is None:
        return DEFAULT_REDACT
    return frozenset(field.strip() for field in raw.split(",") if field.strip())


def _trust(raw: str | None) -> dict[str, TrustLevel]:
    overrides: dict[str, TrustLevel] = {}
    for item in (raw or "").split(","):
        name, sep, level = item.partition("=")
        if sep and name.strip():
            overrides[name.strip()] = TrustLevel(level.strip().lower())
    return overrides
