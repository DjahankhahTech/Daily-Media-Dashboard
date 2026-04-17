"""Unit tests for URL normalization and content hashing."""

from ccmd_dashboard.ingest.dedupe import content_hash, normalize_url


def test_normalize_strips_tracking_and_fragment() -> None:
    u = "HTTPS://Example.COM/Story?utm_source=rss&utm_medium=x&foo=bar#top"
    assert normalize_url(u) == "https://example.com/Story?foo=bar"


def test_normalize_drops_trailing_slash_but_keeps_root() -> None:
    assert normalize_url("https://example.com/a/b/") == "https://example.com/a/b"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_content_hash_stable_across_whitespace_and_case() -> None:
    a = content_hash("Taiwan Strait", "The PLA Navy conducted drills today.")
    b = content_hash("  taiwan   strait ", "the pla navy  conducted drills today.\n")
    assert a == b


def test_content_hash_differs_on_different_titles() -> None:
    a = content_hash("Story A", "Body text that is identical.")
    b = content_hash("Story B", "Body text that is identical.")
    assert a != b


def test_content_hash_ignores_body_beyond_500_chars() -> None:
    body_a = "same prefix " * 20  # ~240 chars -> within window
    body_b = body_a + "different tail content " * 200  # differs well past 500
    # truncated window still identical -> hashes match.
    prefix_a = body_a.strip()
    prefix_b = body_b[: len(prefix_a)]
    assert content_hash("t", prefix_a) == content_hash("t", prefix_b)
