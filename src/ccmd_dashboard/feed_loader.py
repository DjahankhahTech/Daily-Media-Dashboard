"""Loader for feeds.yaml. Supports ``todo: true`` markers so unverified
source URLs can be staged in the config without being ingested."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import settings


@dataclass
class FeedDefinition:
    name: str
    url: str
    source_tier: int
    state_affiliation: str | None = None
    language: str = "en"
    notes: str | None = None
    todo: bool = False  # True = URL unverified; do not fetch until confirmed.


def load_feed_definitions(path: Path | None = None) -> list[FeedDefinition]:
    path = path or (settings.config_dir / "feeds.yaml")
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    out: list[FeedDefinition] = []
    for entry in raw.get("feeds", []):
        out.append(
            FeedDefinition(
                name=entry["name"],
                url=entry["url"],
                source_tier=int(entry["source_tier"]),
                state_affiliation=entry.get("state_affiliation"),
                language=entry.get("language", "en"),
                notes=entry.get("notes"),
                todo=bool(entry.get("todo", False)),
            )
        )
    return out
