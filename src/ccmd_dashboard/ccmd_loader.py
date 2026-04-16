"""Loader for ccmd_aor.yaml. Keeps the AOR definition out of Python source
so analysts can edit keyword lists without touching code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import settings
from .models import AORType


@dataclass
class CCMDDefinition:
    code: str
    name: str
    aor_type: AORType
    description: str = ""
    countries: list[str] = field(default_factory=list)
    regional_keywords: list[str] = field(default_factory=list)
    functional_domains: list[str] = field(default_factory=list)
    adversary_keywords: list[str] = field(default_factory=list)

    @property
    def all_keywords(self) -> list[str]:
        return [
            *self.regional_keywords,
            *self.functional_domains,
            *self.adversary_keywords,
        ]


def _coerce_type(value: str) -> AORType:
    return AORType.FUNCTIONAL if value.lower() == "functional" else AORType.GEOGRAPHIC


def load_ccmd_definitions(path: Path | None = None) -> list[CCMDDefinition]:
    path = path or (settings.config_dir / "ccmd_aor.yaml")
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    results: list[CCMDDefinition] = []
    for entry in raw.get("ccmds", []):
        results.append(
            CCMDDefinition(
                code=entry["code"],
                name=entry["name"],
                aor_type=_coerce_type(entry.get("aor_type", "geographic")),
                description=entry.get("description", ""),
                countries=list(entry.get("countries", []) or []),
                regional_keywords=list(entry.get("regional_keywords", []) or []),
                functional_domains=list(entry.get("functional_domains", []) or []),
                adversary_keywords=list(entry.get("adversary_keywords", []) or []),
            )
        )
    return results
