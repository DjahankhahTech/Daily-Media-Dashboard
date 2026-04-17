"""Anthropic-backed classifier.

Implementation notes
--------------------
* Uses the Anthropic Python SDK's ``client.messages.parse()`` to constrain
  the response to ``MDMExtraction``. That guarantees valid Pydantic output
  without manual JSON repair.
* The system prompt is split into a **stable** block (rubric, output
  rules) and a **volatile** block (per-article metadata). ``cache_control``
  is attached to the stable block so repeated assessments against the same
  model amortize the prompt cost across runs.
* Default model is ``claude-opus-4-7`` with adaptive thinking (``{type:
  "adaptive"}``). ``temperature`` / ``top_p`` / ``budget_tokens`` are
  intentionally absent — they are removed on Opus 4.7 and would 400.
* The prompt forbids the model from making a misinformation judgment.
  Stage 2 (deterministic scorer) does the scoring. The Classifier only
  extracts features.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..config import settings
from .classifier import ArticleForExtraction
from .mdm_types import MDMExtraction

log = logging.getLogger(__name__)


_STABLE_SYSTEM = """\
You are an information-analysis feature extractor for the CCMD Media
Intelligence Dashboard, an unclassified open-source prototype.

Your job is to extract STRUCTURED FEATURES from an article. You DO NOT
assess whether the article is misinformation, disinformation, or
propaganda. That assessment is performed downstream by a deterministic
scorer that combines your output with source metadata. Do not state,
imply, or hedge about the article's truthfulness, credibility, or
intent.

For every article, extract:
  - verifiable_claims: concrete factual claims with their in-article
    attribution (who the article says made the claim; NOT whether the
    claim itself is true).
  - emotional_language: direct quotes of loaded or emotionally charged
    words/phrases. Copy verbatim; do not paraphrase.
  - logical_fallacies: named fallacies (ad hominem, strawman, false
    dichotomy, appeal to emotion, etc.) with a direct quote.
  - unsourced_assertions: factual claims presented without attribution.
  - temporal_claims: time- or date-referenced claims.
  - source_transparency_score (0-3):
      0 = no named sources, no attribution.
      1 = mostly anonymous or "sources familiar with the matter".
      2 = mostly named sources with affiliations.
      3 = multiple named sources + documentary citations.
  - anomalies: other notable items (missing context, framing quirks,
    self-contradictions). Keep the list short.

Rules:
  - Output exactly the MDMExtraction schema. No prose.
  - If a list is genuinely empty, return [].
  - Prefer precision over recall.
  - Do not invent facts that are not in the article text.
"""


def _render_user_block(article: ArticleForExtraction) -> str:
    meta_lines = [
        f"source: {article.source_name or 'unknown'}",
        f"source_tier: {article.source_tier}",
    ]
    if article.state_affiliation:
        meta_lines.append(f"state_affiliation: {article.state_affiliation}")
    if article.published_at_iso:
        meta_lines.append(f"published_at: {article.published_at_iso}")
    meta = "\n".join(meta_lines)
    body = (article.body or "").strip()
    return (
        f"---METADATA---\n{meta}\n\n"
        f"---TITLE---\n{article.title}\n\n"
        f"---BODY---\n{body}\n\n"
        "Extract the MDMExtraction fields from the article above."
    )


class AnthropicClassifier:
    """Classifier implementation backed by the Anthropic API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - extras gate
            raise RuntimeError(
                "anthropic SDK not installed; install with "
                "`uv sync --extra classify`"
            ) from exc

        key = api_key or settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set; cannot use AnthropicClassifier. "
                "Set CCMD_CLASSIFIER=stub for offline mode."
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or settings.anthropic_model
        self.version = f"anthropic:{self._model}"

    def extract(self, article: ArticleForExtraction) -> MDMExtraction:
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _STABLE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user = _render_user_block(article)

        # messages.parse enforces the MDMExtraction schema.
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
            output_format=MDMExtraction,
        )
        parsed = getattr(response, "parsed_output", None)
        if not isinstance(parsed, MDMExtraction):
            # messages.parse should always return an MDMExtraction; if it
            # didn't, surface a hard error rather than silently producing
            # an empty assessment.
            raise RuntimeError(
                f"classifier did not return MDMExtraction: {type(parsed)!r}"
            )
        usage = getattr(response, "usage", None)
        if usage is not None:
            log.info(
                "anthropic classifier usage: in=%s cache_read=%s cache_write=%s out=%s",
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
                getattr(usage, "cache_creation_input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )
        return parsed
