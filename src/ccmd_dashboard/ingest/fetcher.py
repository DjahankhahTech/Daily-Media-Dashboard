"""HTTP fetching with per-domain rate limiting and bounded retry.

Notes
-----
* Per-domain rate limiter is in-process only. When the prototype is ported to
  a production stack this becomes a shared limiter (Redis / similar).
* Retries are bounded and exponential; we do NOT retry on 4xx except 429.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import httpx

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    encoding: Optional[str]
    final_url: str


class _DomainRateLimiter:
    """Enforce a minimum interval between requests to the same host."""

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval = min_interval_seconds
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = defaultdict(float)

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        with self._lock:
            now = time.monotonic()
            wait_until = self._next_allowed[host]
            delay = max(0.0, wait_until - now)
            self._next_allowed[host] = max(now, wait_until) + self.min_interval
        if delay > 0:
            time.sleep(delay)


class Fetcher:
    """Thin wrapper over httpx.Client with rate limiting + retry."""

    def __init__(
        self,
        timeout: float | None = None,
        user_agent: str | None = None,
        per_domain_interval: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.timeout = timeout or settings.http_timeout_seconds
        self.user_agent = user_agent or settings.user_agent
        self.max_retries = max_retries
        self._limiter = _DomainRateLimiter(
            per_domain_interval or settings.per_domain_min_interval_seconds
        )
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, url: str) -> FetchResult:
        """GET with rate limiting + retry. Raises on final failure."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._limiter.wait(url)
            try:
                resp = self._client.get(url)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("fetch %s attempt %d failed: %s", url, attempt, exc)
            else:
                if resp.status_code < 400:
                    return FetchResult(
                        url=url,
                        status_code=resp.status_code,
                        content=resp.content,
                        content_type=resp.headers.get("content-type", ""),
                        encoding=resp.encoding,
                        final_url=str(resp.url),
                    )
                # Retry only on transient server errors and rate-limit.
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                last_exc = httpx.HTTPStatusError(
                    f"status {resp.status_code}", request=resp.request, response=resp
                )
                log.warning("fetch %s attempt %d got %d", url, attempt, resp.status_code)
            # Exponential backoff: 1s, 2s, 4s, ...
            if attempt < self.max_retries:
                time.sleep(2 ** (attempt - 1))
        assert last_exc is not None
        raise last_exc
