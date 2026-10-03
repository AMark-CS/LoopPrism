"""Configuration management for loopprism.

Reads from environment variables and ~/.loopprism/config.toml.
"""

import os
import tomllib
from pathlib import Path
from typing import Optional


def _default_db_path() -> str:
    """Default SQLite database path."""
    current = Path.home() / ".loopprism" / "traces.db"
    legacy = Path.home() / ".toolglass" / "traces.db"
    return str(legacy if not current.exists() and legacy.exists() else current)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Prefer LoopPrism variables while accepting the former prefix."""
    return os.getenv(name, os.getenv(name.replace("LOOPPRISM_", "TOOLGLASS_"), default))


def _default_config_dir() -> Path:
    """Locate configuration without writing to disk on import."""
    return Path.home() / ".loopprism"


class Config:
    """Global loopprism configuration."""

    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        """Load configuration from env vars and config file."""
        # --- Proxy ---
        self.proxy_port: int = int(
            _env("LOOPPRISM_PROXY_PORT", "4317"),
        )
        self.proxy_host: str = _env(
            "LOOPPRISM_PROXY_HOST",
            "127.0.0.1",
        )

        # --- Dashboard ---
        self.dashboard_port: int = int(
            _env("LOOPPRISM_DASHBOARD_PORT", "8080"),
        )
        self.dashboard_enabled: bool = (
            _env("LOOPPRISM_NO_DASHBOARD", "").lower() != "true"
        )

        # --- Storage ---
        self.db_path: str = _env(
            "LOOPPRISM_DB_PATH",
            _default_db_path(),
        )

        # --- Export ---
        self.otlp_endpoint: Optional[str] = _env(
            "LOOPPRISM_OTLP_ENDPOINT",
        )

        # --- Display ---
        self.verbose: bool = (
            _env("LOOPPRISM_VERBOSE", "").lower() == "true"
        )

        # --- Retention ---
        self.max_traces: int = int(
            _env("LOOPPRISM_MAX_TRACES", "100000"),
        )
        self.retention_days: int = int(
            _env("LOOPPRISM_RETENTION_DAYS", "30"),
        )

        # Load config file if it exists (overrides defaults but not env vars)
        config_file = _default_config_dir() / "config.toml"
        if not config_file.exists():
            config_file = Path.home() / ".toolglass" / "config.toml"
        if config_file.exists():
            self._load_file(config_file)

    def _load_file(self, path: Path) -> None:
        """Load config from a TOML file. Does NOT override env vars."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        proxy = data.get("proxy", {})
        if not _env("LOOPPRISM_PROXY_PORT"):
            self.proxy_port = proxy.get("port", self.proxy_port)

        dashboard = data.get("dashboard", {})
        if not _env("LOOPPRISM_DASHBOARD_PORT"):
            self.dashboard_port = dashboard.get("port", self.dashboard_port)

        storage = data.get("storage", {})
        if not _env("LOOPPRISM_DB_PATH"):
            self.db_path = storage.get("db_path", self.db_path)

        if not _env("LOOPPRISM_OTLP_ENDPOINT"):
            self.otlp_endpoint = data.get("export", {}).get(
                "otlp_endpoint",
                self.otlp_endpoint,
            )

        retention = data.get("retention", {})
        if not _env("LOOPPRISM_MAX_TRACES"):
            self.max_traces = retention.get("max_traces", self.max_traces)
        if not _env("LOOPPRISM_RETENTION_DAYS"):
            self.retention_days = retention.get(
                "retention_days",
                self.retention_days,
            )


# Singleton
config = Config()
