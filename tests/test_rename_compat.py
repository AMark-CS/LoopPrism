"""Ensure renaming preserves existing local configuration."""

from pathlib import Path

from loopprism.utils.config import Config, _default_db_path, _env


def test_legacy_environment_and_new_precedence(monkeypatch):
    monkeypatch.delenv("LOOPPRISM_PROXY_PORT", raising=False)
    monkeypatch.setenv("TOOLGLASS_PROXY_PORT", "4444")
    assert _env("LOOPPRISM_PROXY_PORT") == "4444"
    monkeypatch.setenv("LOOPPRISM_PROXY_PORT", "5555")
    assert _env("LOOPPRISM_PROXY_PORT") == "5555"


def test_existing_database_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    legacy = tmp_path / ".toolglass" / "traces.db"
    legacy.parent.mkdir()
    legacy.touch()
    assert _default_db_path() == str(legacy)
    current = tmp_path / ".loopprism" / "traces.db"
    current.parent.mkdir()
    current.touch()
    assert _default_db_path() == str(current)


def test_legacy_config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("LOOPPRISM_PROXY_PORT", raising=False)
    monkeypatch.delenv("TOOLGLASS_PROXY_PORT", raising=False)
    legacy = tmp_path / ".toolglass" / "config.toml"
    legacy.parent.mkdir()
    legacy.write_text("[proxy]\nport = 4567\n")
    assert Config().proxy_port == 4567
