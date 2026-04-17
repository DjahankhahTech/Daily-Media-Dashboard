"""AOR tagger: map articles to 0, 1, or multiple CCMDs.

Signals
-------
1. spaCy NER entities (GPE, ORG, PERSON, LOC, FAC, EVENT, NORP) matched
   against each CCMD's country list (ISO-3166) and keyword lists.
2. Plain-text keyword match against regional_keywords, functional_domains,
   and adversary_keywords.

Score
-----
    score = (2 * entity_matches + keyword_matches) / length_norm
    length_norm = max(1, log10(word_count + 10))

Entity matches are weighted 2x because the NER model has already resolved
ambiguity (e.g., "Jordan" the country vs "Jordan" the person). Keyword
matches are cheap and high-recall but noisier.

An article below ``aor_min_match_score`` against every CCMD goes to the
Unassigned bucket, which the UI surfaces as a diagnostic.
"""

import logging
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional

from ..ccmd_loader import CCMDDefinition, load_ccmd_definitions
from ..config import settings

log = logging.getLogger(__name__)

_COUNTRY_NAMES = {
    "AF": ["Afghanistan"], "BH": ["Bahrain"], "EG": ["Egypt"], "IR": ["Iran"],
    "IQ": ["Iraq"], "JO": ["Jordan"], "KW": ["Kuwait"], "LB": ["Lebanon"],
    "OM": ["Oman"], "PK": ["Pakistan"], "QA": ["Qatar"], "SA": ["Saudi Arabia"],
    "SY": ["Syria"], "AE": ["United Arab Emirates", "UAE"], "YE": ["Yemen"],
    "JP": ["Japan"], "KR": ["South Korea", "Republic of Korea"],
    "KP": ["North Korea", "DPRK"], "CN": ["China", "PRC"],
    "TW": ["Taiwan", "ROC"], "PH": ["Philippines"], "VN": ["Vietnam"],
    "TH": ["Thailand"], "AU": ["Australia"], "NZ": ["New Zealand"],
    "IN": ["India"], "ID": ["Indonesia"], "MY": ["Malaysia"], "SG": ["Singapore"],
    "MN": ["Mongolia"], "GB": ["United Kingdom", "Britain", "UK"], "FR": ["France"],
    "DE": ["Germany"], "IT": ["Italy"], "ES": ["Spain"], "PL": ["Poland"],
    "NL": ["Netherlands"], "NO": ["Norway"], "SE": ["Sweden"], "FI": ["Finland"],
    "DK": ["Denmark"], "UA": ["Ukraine"], "RU": ["Russia", "Russian Federation"],
    "BY": ["Belarus"], "MD": ["Moldova"], "GE": ["Georgia"],
    "US": ["United States", "USA", "U.S."], "CA": ["Canada"], "MX": ["Mexico"],
    "AR": ["Argentina"], "BR": ["Brazil"], "CL": ["Chile"], "CO": ["Colombia"],
    "VE": ["Venezuela"], "PE": ["Peru"], "EC": ["Ecuador"],
    "NG": ["Nigeria"], "ET": ["Ethiopia"], "KE": ["Kenya"], "SO": ["Somalia"],
    "SD": ["Sudan"], "SS": ["South Sudan"], "LY": ["Libya"], "ML": ["Mali"],
    "NE": ["Niger"], "BF": ["Burkina Faso"], "DJ": ["Djibouti"], "ZA": ["South Africa"],
}

_ENTITY_LABELS = {"GPE", "ORG", "PERSON", "LOC", "FAC", "EVENT", "NORP"}


@dataclass
class AORMatch:
    ccmd_code: str
    score: float
    matched_terms: list[str] = field(default_factory=list)
    entity_hits: int = 0
    keyword_hits: int = 0


@dataclass
class _CompiledCCMD:
    code: str
    country_aliases: set[str]  # lowercased
    keywords: list[str]  # lowercased, longest-first for token matching
    keyword_patterns: list[re.Pattern]  # word-boundary regexes


def _compile(defs: list[CCMDDefinition]) -> list[_CompiledCCMD]:
    compiled: list[_CompiledCCMD] = []
    for d in defs:
        aliases: set[str] = set()
        for iso in d.countries:
            for name in _COUNTRY_NAMES.get(iso.upper(), []):
                aliases.add(name.lower())
            aliases.add(iso.lower())
        kw_list = sorted({k.strip() for k in d.all_keywords if k.strip()},
                         key=lambda s: -len(s))
        patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in kw_list]
        compiled.append(
            _CompiledCCMD(
                code=d.code,
                country_aliases=aliases,
                keywords=[k.lower() for k in kw_list],
                keyword_patterns=patterns,
            )
        )
    return compiled


@lru_cache(maxsize=1)
def _compiled() -> list[_CompiledCCMD]:
    return _compile(load_ccmd_definitions())


@lru_cache(maxsize=1)
def _spacy_nlp():
    try:
        import spacy  # type: ignore
    except ImportError:
        log.warning(
            "spaCy not installed; tagger running in keyword-only mode. "
            "Install with `uv sync --extra classify`."
        )
        return None

    for model in (settings.spacy_model, settings.spacy_fallback_model):
        try:
            log.info("loading spaCy model %s", model)
            return spacy.load(model, disable=["parser", "lemmatizer"])
        except OSError:
            log.warning("spaCy model %s not installed", model)
    log.warning("no spaCy model available; tagger running in keyword-only mode")
    return None


def _extract_entities(text: str) -> list[tuple[str, str]]:
    nlp = _spacy_nlp()
    if nlp is None:
        return []
    # Cap input to avoid pathological allocations on huge articles.
    doc = nlp(text[:20000])
    return [(ent.text.strip(), ent.label_) for ent in doc.ents if ent.label_ in _ENTITY_LABELS]


def tag_article(
    title: str,
    body: str,
    *,
    definitions: Optional[Iterable[_CompiledCCMD]] = None,
    min_score: Optional[float] = None,
) -> list[AORMatch]:
    """Return AOR matches for an article above ``min_score``.

    Deterministic: given identical inputs + model, always returns the same
    list. Multiple CCMDs can be returned for cross-AOR stories.
    """
    compiled = list(definitions) if definitions is not None else _compiled()
    threshold = min_score if min_score is not None else settings.aor_min_match_score

    full_text = f"{title}\n\n{body or ''}"
    lower_text = full_text.lower()
    word_count = max(1, len(re.findall(r"\w+", full_text)))
    length_norm = max(1.0, math.log10(word_count + 10))

    entities = _extract_entities(full_text)

    matches: list[AORMatch] = []
    for cc in compiled:
        matched_terms: list[str] = []
        entity_hits = 0
        keyword_hits = 0

        # Entity-based match against country aliases + keyword list.
        for ent_text, _ in entities:
            ent_lower = ent_text.lower()
            if ent_lower in cc.country_aliases:
                entity_hits += 1
                if ent_text not in matched_terms:
                    matched_terms.append(ent_text)
            elif ent_lower in cc.keywords:
                entity_hits += 1
                if ent_text not in matched_terms:
                    matched_terms.append(ent_text)

        # Keyword-based match (word-boundary regex, case-insensitive).
        seen_kw: set[str] = set()
        for pat, kw in zip(cc.keyword_patterns, cc.keywords):
            if pat.search(lower_text):
                keyword_hits += 1
                if kw not in seen_kw:
                    seen_kw.add(kw)
                    if kw not in (m.lower() for m in matched_terms):
                        matched_terms.append(kw)

        raw = (2 * entity_hits + keyword_hits) / length_norm
        score = round(raw, 4)
        if score >= threshold and (entity_hits + keyword_hits) > 0:
            matches.append(
                AORMatch(
                    ccmd_code=cc.code,
                    score=score,
                    matched_terms=matched_terms[:20],  # cap for UI
                    entity_hits=entity_hits,
                    keyword_hits=keyword_hits,
                )
            )
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


TAGGER_VERSION = "aor_tagger_v1"
