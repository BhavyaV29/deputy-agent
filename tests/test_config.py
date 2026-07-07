"""Configuration resolves from the environment with local-first defaults."""

from __future__ import annotations

from pathlib import Path

from deputy.config import DEFAULT_EMBEDDINGS_MODEL, DeputyConfig


def test_defaults_live_under_the_data_dir(tmp_path: Path) -> None:
    config = DeputyConfig.from_env({}, base=tmp_path)
    root = tmp_path.resolve()

    assert config.data_dir == root / "data"
    assert config.workspace_root == root / "sample_workspace"
    assert config.notes_path == root / "data" / "notes.jsonl"
    assert config.calendar_path == root / "data" / "calendar.json"
    assert config.index_path == root / "data" / "index.db"
    assert config.embeddings_model == DEFAULT_EMBEDDINGS_MODEL
    assert config.web_search_enabled is False


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
