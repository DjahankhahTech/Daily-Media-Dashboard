"""Tests for the Classifier interface, stub, and factory.

The Anthropic implementation is NOT tested here — it requires a live API
key. It is exercised by hand and by the integration in step 6.
"""

from ccmd_dashboard.classify.classifier import (
    ArticleForExtraction,
    Classifier,
    get_classifier,
)
from ccmd_dashboard.classify.mdm_types import MDMExtraction
from ccmd_dashboard.classify.stub_classifier import StubClassifier


def test_stub_conforms_to_classifier_protocol() -> None:
    stub = StubClassifier()
    assert isinstance(stub, Classifier)
    assert stub.version.startswith("stub")


def test_stub_extracts_deterministic_output() -> None:
    art = ArticleForExtraction(
        title="CENTCOM announces interdiction in Red Sea",
        body=(
            "CENTCOM announced that U.S. forces intercepted multiple Houthi "
            "drones on Monday. According to U.S. Central Command, the strike "
            "targeted command-and-control infrastructure. Officials launched "
            "a retaliatory operation. The group has been called vile and "
            "reckless in prior statements. Either the group stands down or "
            "further action will follow."
        ),
        source_name="DoD News",
        source_tier=1,
        published_at_iso="2026-04-14",
    )
    result1 = StubClassifier().extract(art)
    result2 = StubClassifier().extract(art)
    assert result1 == result2
    assert isinstance(result1, MDMExtraction)

    # Attribution picked up on "U.S. Central Command".
    attributed = [c for c in result1.verifiable_claims if c.attributed_source]
    assert attributed, "expected at least one attributed claim"

    # Emotional language lexicon hits "vile" and "reckless".
    el_lower = {e.lower() for e in result1.emotional_language}
    assert "vile" in el_lower
    assert "reckless" in el_lower

    # False-dichotomy pattern triggers on "Either X or Y".
    fallacy_types = {f.type for f in result1.logical_fallacies}
    assert "false dichotomy" in fallacy_types

    # Temporal claim picks up "Monday".
    assert result1.temporal_claims

    # Score bounded.
    assert 0 <= result1.source_transparency_score <= 3


def test_stub_flags_state_affiliation_in_anomalies() -> None:
    art = ArticleForExtraction(
        title="State news reports successful launch",
        body="A launch occurred yesterday.",
        source_name="TASS",
        source_tier=3,
        state_affiliation="RU",
    )
    result = StubClassifier().extract(art)
    assert any("RU" in a or "state" in a.lower() for a in result.anomalies)


def test_stub_empty_article_returns_zero_transparency() -> None:
    result = StubClassifier().extract(
        ArticleForExtraction(title="", body="")
    )
    assert result.source_transparency_score == 0
    assert result.verifiable_claims == []
    assert result.emotional_language == []


def test_get_classifier_defaults_to_stub(monkeypatch) -> None:
    from ccmd_dashboard.config import settings as global_settings

    monkeypatch.setattr(global_settings, "classifier", "stub")
    c = get_classifier()
    assert isinstance(c, StubClassifier)


def test_get_classifier_falls_back_on_missing_key(monkeypatch) -> None:
    """If classifier=anthropic but no API key is available, factory must
    fall back to the stub rather than crashing the demo."""
    from ccmd_dashboard.config import settings as global_settings

    monkeypatch.setattr(global_settings, "classifier", "anthropic")
    monkeypatch.setattr(global_settings, "anthropic_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = get_classifier()
    assert isinstance(c, StubClassifier)
