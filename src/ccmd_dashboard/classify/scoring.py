"""Stage-2 deterministic scorer.

The LLM does not produce a concern_score. This module combines:

  * source_tier             (from Feed)
  * state_affiliation       (from Feed)
  * source_transparency     (from MDMExtraction)
  * unsourced_assertions    (from MDMExtraction)
  * logical_fallacies       (from MDMExtraction)
  * emotional_language      (from MDMExtraction)
  * corroboration_count     (from corroborate.py, zero-indexed — 0 means
                             no other feeds in the last window ran the
                             same story)
  * temporal_claims         (from MDMExtraction — used only to detect
                             absence of dating, which weighs against the
                             piece)

...into a concern_score in [0, 100] and maps it to an MDMCategory band.

Every weight and every contribution is returned in the breakdown so the
UI can render an auditable reasoning table. This is the explainability
guarantee: no sub-signal that affects the score is hidden.

Weights are intentionally editable constants at the top of the file; a
future step-9 pass will tune them against an eval set. Document every
weight change in git history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import INSUFFICIENT_DATA, MDM_CATEGORY_BANDS
from ..models import MDMCategory
from .mdm_types import MDMExtraction


# ---------------------------------------------------------------------------
# Weights (edit here — do not scatter magic numbers into the scorer body).
# Each weight = maximum points the signal can contribute to concern_score.
# ---------------------------------------------------------------------------

W_SOURCE_TIER_3 = 10        # tier 3 non-state: small baseline penalty
W_STATE_AFFILIATION = 25    # state-affiliated source: large penalty
W_LOW_TRANSPARENCY = 20     # per missing transparency point (0..3)
W_UNSOURCED_ASSERTIONS = 15 # saturates after 5 unsourced assertions
W_LOGICAL_FALLACY = 10      # 3 points per fallacy, capped at this weight
W_EMOTIONAL_LANGUAGE = 10   # 2 points per loaded-language quote, capped
W_LOW_CORROBORATION = 15    # 0 other feeds: full penalty; falls to 0 at >=3
W_MISSING_TEMPORAL = 5      # no dated claims at all: small penalty


@dataclass
class SubSignal:
    name: str
    value: Any
    weight: int
    contribution: int
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "explanation": self.explanation,
        }


@dataclass
class ScoreInput:
    source_tier: int
    state_affiliation: str | None
    extraction: MDMExtraction
    corroboration_count: int


@dataclass
class ScoreResult:
    concern_score: int
    category: MDMCategory
    sub_signals: list[SubSignal]

    def reasoning_breakdown(self) -> dict[str, Any]:
        return {
            "sub_signals": [s.as_dict() for s in self.sub_signals],
            "total": self.concern_score,
            "category": self.category.value,
        }


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def _band(score: int) -> MDMCategory:
    for lo, hi, name in MDM_CATEGORY_BANDS:
        if lo <= score <= hi:
            return MDMCategory(name)
    return MDMCategory(INSUFFICIENT_DATA)


# ---------------------------------------------------------------------------
# Sub-signal computations
# ---------------------------------------------------------------------------


def _signal_source_tier(tier: int) -> SubSignal:
    if tier >= 3:
        return SubSignal(
            name="source_tier",
            value=tier,
            weight=W_SOURCE_TIER_3,
            contribution=W_SOURCE_TIER_3,
            explanation=f"Tier {tier} source — wire/regional/non-USG, small baseline penalty.",
        )
    return SubSignal(
        name="source_tier",
        value=tier,
        weight=W_SOURCE_TIER_3,
        contribution=0,
        explanation=f"Tier {tier} source — USG or vetted trade press, no penalty.",
    )


def _signal_state_affiliation(state: str | None) -> SubSignal:
    if state:
        return SubSignal(
            name="state_affiliation",
            value=state,
            weight=W_STATE_AFFILIATION,
            contribution=W_STATE_AFFILIATION,
            explanation=f"Feed is affiliated with state {state}.",
        )
    return SubSignal(
        name="state_affiliation",
        value=None,
        weight=W_STATE_AFFILIATION,
        contribution=0,
        explanation="No known state affiliation.",
    )


def _signal_transparency(score: int | None) -> SubSignal:
    if score is None:
        return SubSignal(
            name="source_transparency",
            value=None,
            weight=W_LOW_TRANSPARENCY,
            contribution=W_LOW_TRANSPARENCY,
            explanation="No transparency score available; treated as worst case.",
        )
    # 3 -> 0 pts, 0 -> full weight, linear between.
    contribution = int(round(W_LOW_TRANSPARENCY * (3 - score) / 3))
    return SubSignal(
        name="source_transparency",
        value=score,
        weight=W_LOW_TRANSPARENCY,
        contribution=contribution,
        explanation=f"Transparency score {score}/3 (0=opaque, 3=fully sourced).",
    )


def _signal_unsourced(extraction: MDMExtraction) -> SubSignal:
    n = len(extraction.unsourced_assertions)
    contribution = min(W_UNSOURCED_ASSERTIONS, n * 3)
    return SubSignal(
        name="unsourced_assertions",
        value=n,
        weight=W_UNSOURCED_ASSERTIONS,
        contribution=contribution,
        explanation=(
            f"{n} unsourced assertion(s) identified. "
            "Capped at 5 instances."
        ),
    )


def _signal_fallacies(extraction: MDMExtraction) -> SubSignal:
    n = len(extraction.logical_fallacies)
    contribution = min(W_LOGICAL_FALLACY, n * 3)
    types = sorted({f.type for f in extraction.logical_fallacies})
    return SubSignal(
        name="logical_fallacies",
        value=n,
        weight=W_LOGICAL_FALLACY,
        contribution=contribution,
        explanation=(
            f"{n} fallacy instance(s): {', '.join(types) if types else 'none'}."
        ),
    )


def _signal_emotional(extraction: MDMExtraction) -> SubSignal:
    n = len(extraction.emotional_language)
    contribution = min(W_EMOTIONAL_LANGUAGE, n * 2)
    return SubSignal(
        name="emotional_language",
        value=n,
        weight=W_EMOTIONAL_LANGUAGE,
        contribution=contribution,
        explanation=(
            f"{n} loaded-language quote(s). Capped at 5 instances."
        ),
    )


def _signal_corroboration(count: int) -> SubSignal:
    # 0 other feeds: full penalty
    # 1: 2/3 penalty
    # 2: 1/3 penalty
    # 3+: 0 penalty
    if count >= 3:
        contribution = 0
    elif count <= 0:
        contribution = W_LOW_CORROBORATION
    else:
        contribution = int(round(W_LOW_CORROBORATION * (3 - count) / 3))
    return SubSignal(
        name="corroboration",
        value=count,
        weight=W_LOW_CORROBORATION,
        contribution=contribution,
        explanation=(
            f"{count} other feed(s) corroborate this story "
            "within the configured time window."
        ),
    )


def _signal_missing_temporal(extraction: MDMExtraction) -> SubSignal:
    if extraction.temporal_claims:
        return SubSignal(
            name="missing_temporal",
            value=len(extraction.temporal_claims),
            weight=W_MISSING_TEMPORAL,
            contribution=0,
            explanation="Article contains dated claims.",
        )
    return SubSignal(
        name="missing_temporal",
        value=0,
        weight=W_MISSING_TEMPORAL,
        contribution=W_MISSING_TEMPORAL,
        explanation="No dated claims — reduces verifiability.",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score(inputs: ScoreInput) -> ScoreResult:
    """Combine all sub-signals into a single concern_score + category."""
    signals = [
        _signal_source_tier(inputs.source_tier),
        _signal_state_affiliation(inputs.state_affiliation),
        _signal_transparency(inputs.extraction.source_transparency_score),
        _signal_unsourced(inputs.extraction),
        _signal_fallacies(inputs.extraction),
        _signal_emotional(inputs.extraction),
        _signal_corroboration(inputs.corroboration_count),
        _signal_missing_temporal(inputs.extraction),
    ]
    total = sum(s.contribution for s in signals)
    clamped = _clamp(total)
    return ScoreResult(
        concern_score=clamped,
        category=_band(clamped),
        sub_signals=signals,
    )


SCORING_VERSION = "scoring-v1"
