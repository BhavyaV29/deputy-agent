"""Configuration resolves from the environment with local-first defaults."""

from __future__ import annotations

from pathlib import Path

from deputy.approvals import TrustLevel
from deputy.audit import DEFAULT_REDACT
from deputy.config import DEFAULT_EMBEDDINGS_MODEL, DeputyConfig


def test_defaults_live_under_the_data_dir(tmp_path: Path) -> None:
    config = DeputyConfig.from_env({}, base=tmp_path)
    root = tmp_path.resolve()

    assert config.data_dir == root / "data"
    assert config.workspace_root == root / "sample_workspace"
    assert config.notes_path == root / "data" / "notes.jsonl"
    assert config.calendar_path == root / "data" / "calendar.json"
    assert config.index_path == root / "data" / "index.db"
    assert config.audit_path == root / "data" / "audit.jsonl"
    assert config.embeddings_model == DEFAULT_EMBEDDINGS_MODEL
    assert config.web_search_enabled is False


def test_trust_surface_defaults_are_local_only(tmp_path: Path) -> None:
    config = DeputyConfig.from_env({}, base=tmp_path)

    assert config.audit_redact == DEFAULT_REDACT
    assert config.trust_overrides == {}
    assert config.cloud_enabled is False
    assert config.cloud_api_key is None
    assert config.cloud_ready is False  # off by default: nothing leaves the device


def test_cloud_needs_both_the_flag_and_a_key() -> None:
    assert DeputyConfig.from_env({"DEPUTY_CLOUD_ENABLED": "1"}).cloud_ready is False
    assert DeputyConfig.from_env({"DEPUTY_CLOUD_API_KEY": "sk-x"}).cloud_ready is False
    opted_in = DeputyConfig.from_env({"DEPUTY_CLOUD_ENABLED": "1", "DEPUTY_CLOUD_API_KEY": "sk-x"})
    assert opted_in.cloud_ready is True


def test_trust_overrides_parse_from_env() -> None:
    config = DeputyConfig.from_env({"DEPUTY_TRUST": "search_files=allow, add_note=deny"})
    assert config.trust_overrides == {
        "search_files": TrustLevel.ALLOW,
        "add_note": TrustLevel.DENY,
    }


def test_audit_redaction_set_is_overridable() -> None:
    config = DeputyConfig.from_env({"DEPUTY_AUDIT_REDACT": "ssn, pin"})
    assert config.audit_redact == frozenset({"ssn", "pin"})


def test_env_overrides_win(tmp_path: Path) -> None:
    env = {
        "DEPUTY_DATA_DIR": str(tmp_path / "d"),
        "DEPUTY_WORKSPACE_ROOT": str(tmp_path / "ws"),
        "DEPUTY_EMBEDDINGS_MODEL": "custom-embed",
        "DEPUTY_WEB_SEARCH_ENABLED": "true",
    }
    config = DeputyConfig.from_env(env, base=tmp_path)

    assert config.data_dir == (tmp_path / "d").resolve()
    assert config.workspace_root == (tmp_path / "ws").resolve()
    assert config.embeddings_model == "custom-embed"
    assert config.web_search_enabled is True


def test_web_search_flag_is_permissive_about_truthiness() -> None:
    assert DeputyConfig.from_env({"DEPUTY_WEB_SEARCH_ENABLED": "0"}).web_search_enabled is False
    assert DeputyConfig.from_env({"DEPUTY_WEB_SEARCH_ENABLED": ""}).web_search_enabled is False
    assert DeputyConfig.from_env({"DEPUTY_WEB_SEARCH_ENABLED": "YES"}).web_search_enabled is True
