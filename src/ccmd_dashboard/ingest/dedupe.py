"""Content hashing + URL normalization for dedupe.

Dedupe strategy (two-stage):
1. URL match — strongest signal, fastest check, catches re-emissions of the
   same feed item.
2. content_hash match — catches republications under a different URL (same
   wire story carried by multiple outlets, query-string-only URL changes,
   AMP mirrors, etc.).

The hash is deliberately NOT a hash of the entire body: feed summaries and
full-article extractions for the same story will often differ by boilerplate
(ads, related links, share widgets). Hashing normalized(title) + first 500
normalized body chars gives us a stable, conservative identity signal.
"""

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

_WHITESPACE_RE = re.compile(r"\s+")

# Query parameters we always strip because they carry tracking/session state
# rather than content identity.
_TRACKING_PARAMS_PREFIX = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid")


def normalize_url(url: str) -> str:
    """Lowercase scheme/host, strip fragment, drop tracking query params."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    query = parts.query
    if query:
        kept: list[str] = []
        for pair in query.split("&"):
            if not pair:
                continue
            key = pair.split("=", 1)[0]
            if any(key.lower().startswith(p) for p in _TRACKING_PARAMS_PREFIX):
                continue
            kept.append(pair)
        query = "&".join(kept)
    path = parts.path.rstrip("/") if parts.path != "/" else parts.path
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text or "").strip().lower()


def content_hash(title: str, body: str) -> str:
    """SHA256 of normalized(title) + first 500 chars of normalized(body)."""
    norm_title = _normalize_text(title)
    norm_body = _normalize_text(body)[:500]
    payload = f"{norm_title}||{norm_body}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
