"""Abstract Classifier interface.

Any implementation must produce the same schema (``MDMExtraction``) so the
stage-2 deterministic scorer and the UI can treat the stub and the real
Anthropic implementations identically.

The web layer MUST NOT call a Classifier directly — MDM runs go through
``classify/mdm_runner.py`` which is scheduled as a background job.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .mdm_types import MDMExtraction


@dataclass
class ArticleForExtraction:
    """Everything a classifier needs to extract features from an article."""

    title: str
    body: str
    source_name: str = ""
    source_tier: int = 3
    state_affiliation: str | None = None
    published_at_iso: str | None = None


@runtime_checkable
class Classifier(Protocol):
    """Interface implemented by StubClassifier and AnthropicClassifier."""

    @property
    def version(self) -> str: ...

    def extract(self, article: ArticleForExtraction) -> MDMExtraction: ...


def get_classifier(mode: str | None = None) -> Classifier:
    """Factory that resolves the classifier from settings or the ``mode`` arg.

    - "stub" -> StubClassifier (offline, deterministic)
    - "anthropic" -> AnthropicClassifier (requires ANTHROPIC_API_KEY)

    Unknown values fall back to the stub with a warning so the demo never
    silently produces a broken assessment.
    """
    from ..config import settings
    import logging

    log = logging.getLogger(__name__)

    resolved = (mode or settings.classifier or "stub").lower()
    if resolved == "anthropic":
        try:
            from .anthropic_classifier import AnthropicClassifier
            return AnthropicClassifier()
        except Exception as exc:
            log.warning("falling back to StubClassifier: %s", exc)
    from .stub_classifier import StubClassifier
    return StubClassifier()
