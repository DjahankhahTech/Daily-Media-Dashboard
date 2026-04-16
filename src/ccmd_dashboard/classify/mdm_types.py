"""Stage-1 structured output schema.

These are the features the LLM extracts per article. The deterministic
scorer (stage 2) combines them with source_tier, state_affiliation, and
corroboration count to produce a ``concern_score`` and reasoning breakdown.

The prompt explicitly forbids the LLM from asserting whether an article
is misinformation. It only extracts the features below.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Claim(BaseModel):
    claim: str = Field(description="A factual assertion made in the article.")
    attributed_source: Optional[str] = Field(
        default=None,
        description=(
            "Who the article attributes this claim to (person, agency, "
            "publication). None if unattributed."
        ),
    )


class Fallacy(BaseModel):
    type: str = Field(description="Named logical fallacy, e.g., ad hominem.")
    quote: str = Field(description="Direct quote illustrating the fallacy.")


class TemporalClaim(BaseModel):
    claim: str = Field(description="Claim that references a specific time or date.")
    date_referenced: Optional[str] = Field(
        default=None,
        description="ISO date or date range the claim references, if present.",
    )


class MDMExtraction(BaseModel):
    """What stage 1 returns. Stage 2 consumes this plus source metadata."""

    verifiable_claims: list[Claim] = Field(
        default_factory=list,
        description=(
            "Concrete factual claims in the article, each with the article's "
            "attribution (not whether the claim is actually true)."
        ),
    )
    emotional_language: list[str] = Field(
        default_factory=list,
        description=(
            "Direct quotes of loaded or emotionally charged language used in "
            "the article. Do not paraphrase — copy the exact words."
        ),
    )
    logical_fallacies: list[Fallacy] = Field(
        default_factory=list,
        description="Logical fallacies present in the article's argumentation.",
    )
    unsourced_assertions: list[str] = Field(
        default_factory=list,
        description="Factual claims that the article presents without attribution.",
    )
    temporal_claims: list[TemporalClaim] = Field(
        default_factory=list,
        description="Time- or date-referenced claims.",
    )
    source_transparency_score: int = Field(
        ge=0,
        le=3,
        description=(
            "Rubric: "
            "0 = no named sources, no attribution; "
            "1 = some attribution but mostly anonymous / 'sources familiar'; "
            "2 = mostly named sources with affiliations; "
            "3 = multiple named sources with clear affiliations + "
            "documentary citations."
        ),
    )
    anomalies: list[str] = Field(
        default_factory=list,
        description=(
            "Other notable items (inconsistencies, missing context, "
            "suspicious framing). Use sparingly; include the quote when "
            "possible."
        ),
    )


EXTRACTION_VERSION = "mdm-extract-v1"
