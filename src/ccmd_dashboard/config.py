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
    anthropic_model: str = "claude-opus-4-7"

    # Ingestion
    http_timeout_seconds: float = 10.0
    per_domain_min_interval_seconds: float = 1.0
    user_agent: str = "ccmd-dashboard/0.1 (unclassified prototype; contact: OSW)"

    # Background ingest scheduler (serve-time only; CLI ingest is unaffected)
    ingest_enabled: bool = False
    ingest_interval_minutes: int = 60
    ingest_extract_full: bool = False
    ingest_tag_after: bool = True

    # Corroboration
    corroboration_similarity_threshold: float = 0.70
    corroboration_window_hours: int = 72

    # AOR tagger
    # Prefer en_core_web_trf (transformer, better for named entities in
    # defense text); fall back to en_core_web_sm in dev / offline envs.
    spacy_model: str = "en_core_web_trf"
    spacy_fallback_model: str = "en_core_web_sm"
    aor_min_match_score: float = 0.02

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_feed_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
