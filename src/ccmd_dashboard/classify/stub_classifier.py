"""Offline StubClassifier.

Produces a deterministic ``MDMExtraction`` derived from the article text.
Works with zero dependencies beyond the standard library + Pydantic so
the demo can run in air-gapped environments.

Heuristics are deliberately simple — the point of the stub is to exercise
the UI and the stage-2 scorer, not to be accurate. The dashboard banners
+ About page say as much.
"""

import re
from typing import Iterable

from .classifier import ArticleForExtraction
from .mdm_types import Claim, Fallacy, MDMExtraction, TemporalClaim

_LOADED_TERMS = {
    "brutal", "catastrophic", "disastrous", "unthinkable", "shocking",
    "outrageous", "reckless", "dangerous", "unprecedented", "humiliating",
    "devastating", "treacherous", "cowardly", "heroic", "glorious",
    "imperialist", "regime", "puppet", "terrorist", "vile", "radical",
}
_FALLACY_TRIGGERS = {
    "ad hominem": [r"\b(liar|fool|puppet|coward)\b"],
    "false dichotomy": [r"\b(either\s+.+\s+or)\b"],
    "appeal to emotion": [r"\b(how\s+can\s+anyone|think\s+of\s+the)\b"],
    "strawman": [r"\b(claims?\s+that\s+all)\b"],
}
_ATTRIBUTION_MARKERS = [
    r"according to\s+([A-Z][\w\s]{2,60})",
    r"([A-Z][\w\s]{2,60})\s+said",
    r"([A-Z][\w\s]{2,60})\s+announced",
    r"([A-Z][\w\s]{2,60})\s+told\s+reporters",
    r"a statement from\s+([A-Z][\w\s]{2,60})",
]
_TEMPORAL = re.compile(
    r"\b(today|yesterday|last\s+week|this\s+week|on\s+\w+day|"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:,\s+\d{4})?)\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


class StubClassifier:
    version = "stub-v1"

    def extract(self, article: ArticleForExtraction) -> MDMExtraction:
        full = f"{article.title}\n\n{article.body or ''}"
        sentences = _sentences(full)

        claims: list[Claim] = []
        unsourced: list[str] = []
        for s in sentences:
            attributed = None
            for pattern in _ATTRIBUTION_MARKERS:
                m = re.search(pattern, s)
                if m:
                    attributed = m.group(1).strip()
                    break
            if any(trigger in s.lower() for trigger in (
                "percent", "billion", "million", "killed", "wounded",
                "launched", "deployed", "intercepted", "announced",
            )):
                if attributed:
                    claims.append(Claim(claim=s, attributed_source=attributed))
                else:
                    unsourced.append(s)

        emotional = _unique(
            t for t in _LOADED_TERMS if re.search(rf"\b{t}\b", full, re.IGNORECASE)
        )

        fallacies: list[Fallacy] = []
        for fallacy_type, patterns in _FALLACY_TRIGGERS.items():
            for p in patterns:
                m = re.search(p, full, re.IGNORECASE)
                if m:
                    fallacies.append(
                        Fallacy(type=fallacy_type, quote=m.group(0))
                    )
                    break

        temporal: list[TemporalClaim] = []
        for s in sentences:
            m = _TEMPORAL.search(s)
            if m:
                temporal.append(
                    TemporalClaim(claim=s, date_referenced=m.group(0))
                )

        named_entities = len(re.findall(
            r"\b(?:[A-Z][a-z]+\s){1,3}(?:said|announced|told)\b", full
        ))
        source_transparency_score = min(3, named_entities)
        if not sentences:
            source_transparency_score = 0

        anomalies: list[str] = []
        if article.state_affiliation:
            anomalies.append(
                f"Source {article.source_name or 'unknown'} is affiliated "
                f"with state {article.state_affiliation}."
            )

        return MDMExtraction(
            verifiable_claims=claims[:20],
            emotional_language=emotional[:20],
            logical_fallacies=fallacies[:10],
            unsourced_assertions=unsourced[:20],
            temporal_claims=temporal[:20],
            source_transparency_score=source_transparency_score,
            anomalies=anomalies[:10],
        )
