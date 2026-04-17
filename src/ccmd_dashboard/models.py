"""SQLModel schema for the prototype.

Design notes
------------
* Handling-marking fields (``classification_marking``, ``handling_caveat``,
  ``dissemination_controls``, ``source_reliability``, ``info_credibility``)
  are nullable and default-populated so the schema is ready for a classified
  port without forcing the prototype to expose them in the UI.
* All timestamps are stored as UTC naive datetimes; the ingestion layer
  is responsible for normalizing source-provided timestamps.
* ``reasoning_breakdown`` on MDMAssessment is the canonical audit trail for
  a score — never score without persisting the per-sub-signal table.
* No ``from __future__ import annotations`` here on purpose: SQLModel +
  SQLAlchemy 2.0 resolves relationship target classes from runtime type
  annotations, and stringified annotations break that resolution.
"""

import enum
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import Column, Index, JSON, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.utcnow()


class AORType(str, enum.Enum):
    GEOGRAPHIC = "geographic"
    FUNCTIONAL = "functional"


class MDMCategory(str, enum.Enum):
    LIKELY_RELIABLE = "likely_reliable"
    REQUIRES_VERIFICATION = "requires_verification"
    SIGNIFICANT_CONCERNS = "significant_concerns"
    HIGH_CONCERN = "high_concern"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalystAction(str, enum.Enum):
    REVIEWED = "reviewed"
    FLAGGED_FOR_OIC = "flagged_for_oic"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


class Feed(SQLModel, table=True):
    __tablename__ = "feed"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    url: str = Field(unique=True)
    # 1 = USG official, 2 = trade press, 3 = wire / regional / state-affiliated
    source_tier: int = Field(ge=1, le=3)
    # ISO country code of the state sponsor if the feed is state-affiliated
    # (e.g., "RU" for TASS). None for non-state-affiliated feeds.
    state_affiliation: Optional[str] = Field(default=None, max_length=8)
    language: str = Field(default="en", max_length=8)
    active: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    # Analyst-facing note on the feed itself (provenance, caveats).
    notes: Optional[str] = Field(default=None)

    articles: List["Article"] = Relationship(back_populates="feed")


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


class Article(SQLModel, table=True):
    __tablename__ = "article"
    __table_args__ = (
        UniqueConstraint("url", name="uq_article_url"),
        Index("ix_article_published_at", "published_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: int = Field(foreign_key="feed.id", index=True)

    url: str
    title: str
    author: Optional[str] = Field(default=None)
    published_at: Optional[datetime] = Field(default=None)
    fetched_at: datetime = Field(default_factory=_utcnow)

    raw_text: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    content_hash: str = Field(index=True, max_length=64)
    language: str = Field(default="en", max_length=8)

    # ---- Handling-ready (schema-populated, UI does not expose) ----
    classification_marking: str = Field(default="U", max_length=16)
    handling_caveat: Optional[str] = Field(default=None, max_length=64)
    dissemination_controls: Optional[str] = Field(default=None, max_length=64)
    # NATO admiralty code: source reliability A–F, info credibility 1–6.
    source_reliability: Optional[str] = Field(default=None, max_length=1)
    info_credibility: Optional[str] = Field(default=None, max_length=1)

    feed: Optional[Feed] = Relationship(back_populates="articles")
    ccmd_tags: List["ArticleCCMD"] = Relationship(
        back_populates="article",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    mdm_assessments: List["MDMAssessment"] = Relationship(
        back_populates="article",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    analyst_notes: List["AnalystNote"] = Relationship(
        back_populates="article",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


# ---------------------------------------------------------------------------
# CCMDs and AOR tagging
# ---------------------------------------------------------------------------


class CCMD(SQLModel, table=True):
    __tablename__ = "ccmd"

    code: str = Field(primary_key=True, max_length=16)  # e.g., "INDOPACOM"
    name: str
    aor_type: AORType = Field(default=AORType.GEOGRAPHIC)
    description: Optional[str] = Field(default=None)

    article_links: List["ArticleCCMD"] = Relationship(back_populates="ccmd")


class ArticleCCMD(SQLModel, table=True):
    """Many-to-many between Article and CCMD with match metadata."""

    __tablename__ = "article_ccmd"
    __table_args__ = (
        UniqueConstraint("article_id", "ccmd_code", name="uq_article_ccmd"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True)
    ccmd_code: str = Field(foreign_key="ccmd.code", index=True, max_length=16)
    match_score: float = Field(default=0.0)
    matched_terms: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tagged_by: str = Field(default="aor_tagger_v1", max_length=64)
    tagged_at: datetime = Field(default_factory=_utcnow)

    article: Optional[Article] = Relationship(back_populates="ccmd_tags")
    ccmd: Optional[CCMD] = Relationship(back_populates="article_links")


# ---------------------------------------------------------------------------
# MDM assessments
# ---------------------------------------------------------------------------


class MDMAssessment(SQLModel, table=True):
    __tablename__ = "mdm_assessment"
    __table_args__ = (
        Index("ix_mdm_article_assessed_at", "article_id", "assessed_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True)
    assessed_at: datetime = Field(default_factory=_utcnow)
    classifier_version: str = Field(max_length=64)

    # Stage 1 (LLM extraction) structured output.
    verifiable_claims: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    emotional_language: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    logical_fallacies: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    unsourced_assertions: list[str] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    temporal_claims: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    source_transparency_score: Optional[int] = Field(default=None, ge=0, le=3)

    # Stage 2 (deterministic scorer) inputs.
    corroboration_count: int = Field(default=0)
    corroborating_article_ids: list[int] = Field(
        default_factory=list, sa_column=Column(JSON)
    )

    # Stage 2 outputs.
    concern_score: Optional[int] = Field(default=None, ge=0, le=100)
    category: MDMCategory = Field(default=MDMCategory.INSUFFICIENT_DATA)
    # Sub-signal table: list of {name, value, weight, contribution, explanation}.
    reasoning_breakdown: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    # Free-form failure diagnostics so the UI never silently swallows errors.
    failure_reason: Optional[str] = Field(default=None)

    article: Optional[Article] = Relationship(back_populates="mdm_assessments")


# ---------------------------------------------------------------------------
# Analyst workflow
# ---------------------------------------------------------------------------


class AnalystNote(SQLModel, table=True):
    __tablename__ = "analyst_note"
    __table_args__ = (Index("ix_note_article_created", "article_id", "created_at"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True)
    analyst_id: str = Field(index=True, max_length=64)

    # ATP 2-style structured note fields.
    observation: Optional[str] = Field(default=None)
    significance: Optional[str] = Field(default=None)
    recommended_action: Optional[str] = Field(default=None)

    note: Optional[str] = Field(default=None)
    action_taken: AnalystAction = Field(default=AnalystAction.REVIEWED)
    created_at: datetime = Field(default_factory=_utcnow)

    article: Optional[Article] = Relationship(back_populates="analyst_notes")


# ---------------------------------------------------------------------------
# Ingest audit
# ---------------------------------------------------------------------------


class IngestRun(SQLModel, table=True):
    """One row per ingestion pass over a feed. Supports audit + reprocessing."""

    __tablename__ = "ingest_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: int = Field(foreign_key="feed.id", index=True)
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    articles_seen: int = Field(default=0)
    articles_new: int = Field(default=0)
    raw_feed_path: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
