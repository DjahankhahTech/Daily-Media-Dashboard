"""Runtime configuration loader.

Settings are resolved from environment variables (prefix CCMD_) and
optionally a .env file at the repository root. Paths default to the
repository layout so the prototype runs with zero configuration.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CCMD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Filesystem layout
    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    config_dir: Path = REPO_ROOT / "config"
    raw_feed_dir: Path = REPO_ROOT / "data" / "raw_feeds"

    # Database
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'dashboard.db'}"

    # Classifier selection: "stub" or "anthropic"
    classifier: str = "stub"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # Ingestion
    http_timeout_seconds: float = 10.0
    per_domain_min_interval_seconds: float = 1.0
    user_agent: str = "ccmd-dashboard/0.1 (unclassified prototype; contact: OSW)"

    # Corroboration
    corroboration_similarity_threshold: float = 0.70
    corroboration_window_hours: int = 72

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_feed_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
