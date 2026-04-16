"""Tests for the stage-2 deterministic scorer."""

from ccmd_dashboard.classify.mdm_types import (
    Claim,
    Fallacy,
    MDMExtraction,
    TemporalClaim,
)
from ccmd_dashboard.classify.scoring import ScoreInput, score
from ccmd_dashboard.constants import MDM_CATEGORY_BANDS
from ccmd_dashboard.models import MDMCategory


def _clean_extraction() -> MDMExtraction:
    return MDMExtraction(
        verifiable_claims=[
            Claim(claim="x said y", attributed_source="x"),
        ],
        emotional_language=[],
        logical_fallacies=[],
        unsourced_assertions=[],
        temporal_claims=[TemporalClaim(claim="on Monday", date_referenced="Monday")],
        source_transparency_score=3,
        anomalies=[],
    )


def test_tier1_clean_scores_low() -> None:
    result = score(
        ScoreInput(
            source_tier=1,
            state_affiliation=None,
            extraction=_clean_extraction(),
            corroboration_count=5,
        )
    )
    assert result.concern_score == 0
    assert result.category == MDMCategory.LIKELY_RELIABLE
    # Reasoning breakdown includes every sub-signal even when contribution is 0.
    names = {s.name for s in result.sub_signals}
    assert names == {
        "source_tier", "state_affiliation", "source_transparency",
        "unsourced_assertions", "logical_fallacies", "emotional_language",
        "corroboration", "missing_temporal",
    }


def test_state_media_uncorroborated_scores_high() -> None:
    extraction = MDMExtraction(
        verifiable_claims=[],
        emotional_language=["vile", "reckless", "catastrophic", "puppet"],
        logical_fallacies=[Fallacy(type="ad hominem", quote="puppet regime")],
        unsourced_assertions=[
            "Foreign agents planted the device",
            "NATO coordinated the provocation",
            "Western sources confirm the hoax",
            "The operation failed spectacularly",
            "Civilians were deliberately targeted",
            "Satellite imagery shows otherwise",
        ],
        temporal_claims=[],
        source_transparency_score=0,
        anomalies=[],
    )
    result = score(
        ScoreInput(
            source_tier=3,
            state_affiliation="RU",
            extraction=extraction,
            corroboration_count=0,
        )
    )
    # Tier3 + state + low transparency + heavy unsourced + fallacies +
    # emotional + no corroboration + no dates -> should land in the top
    # two bands.
    assert result.concern_score >= 76
    assert result.category in (
        MDMCategory.HIGH_CONCERN,
        MDMCategory.SIGNIFICANT_CONCERNS,
    )


def test_band_mapping_matches_table() -> None:
    """Scores at every band boundary map to the right category."""
    for lo, hi, name in MDM_CATEGORY_BANDS:
        for probe in (lo, (lo + hi) // 2, hi):
            extraction = MDMExtraction(
                source_transparency_score=3, emotional_language=[],
                unsourced_assertions=[], logical_fallacies=[],
                temporal_claims=[TemporalClaim(claim="today")],
                verifiable_claims=[], anomalies=[],
            )
            # Pick inputs that put the score roughly at the probe; here
            # we just check the score -> category mapper via a manufactured
            # result object.
            from ccmd_dashboard.classify.scoring import _band
            assert _band(probe).value == name


def test_corroboration_monotonic() -> None:
    """More corroborators should never increase the score."""
    extraction = _clean_extraction()
    prev = None
    for c in range(0, 5):
        s = score(
            ScoreInput(
                source_tier=2,
                state_affiliation=None,
                extraction=extraction,
                corroboration_count=c,
            )
        ).concern_score
        if prev is not None:
            assert s <= prev
        prev = s


def test_score_clamped_to_100() -> None:
    """Even with pathological inputs the score must not exceed 100."""
    extraction = MDMExtraction(
        verifiable_claims=[],
        emotional_language=["a"] * 20,
        logical_fallacies=[Fallacy(type="x", quote="q")] * 10,
        unsourced_assertions=["u"] * 20,
        temporal_claims=[],
        source_transparency_score=0,
        anomalies=[],
    )
    result = score(
        ScoreInput(
            source_tier=3, state_affiliation="RU",
            extraction=extraction, corroboration_count=0,
        )
    )
    assert result.concern_score <= 100
