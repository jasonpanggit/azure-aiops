"""Unit tests for `intelligence.vulnerability.enrichment_cache.EnrichmentCache`.

The cache exists so external CVE enrichment (MSRC/NVD/EPSS/KEV) survives a
restart and is shared across replicas rather than each one cold-starting and
multiplying load on rate-limited public feeds. The behaviours worth pinning
are therefore: TTL expiry, that a cached *empty* value is a real hit (negative
caching), durability across process restarts, and that a broken store degrades
to an in-memory cache instead of breaking the caller.
"""

from __future__ import annotations

import pytest

from intelligence.vulnerability.enrichment_cache import EnrichmentCache
from storage.onelake_documents import OneLakeDocumentStore


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_miss_then_hit(tmp_path):
    cache = EnrichmentCache("cache/feed.json", store=OneLakeDocumentStore(tmp_path))
    assert cache.get("CVE-1") == (False, None)

    cache.set("CVE-1", {"score": 1})
    assert cache.get("CVE-1") == (True, {"score": 1})


def test_empty_value_is_a_hit(tmp_path):
    """Negative caching depends on this: an empty payload must be
    distinguishable from an absent key, or a throttled upstream is retried on
    every single request."""
    cache = EnrichmentCache("cache/feed.json", store=OneLakeDocumentStore(tmp_path))
    cache.set("CVE-1", {})

    hit, value = cache.get("CVE-1")
    assert hit is True
    assert value == {}


def test_entry_expires_after_ttl(tmp_path):
    clock = _Clock()
    cache = EnrichmentCache(
        "cache/feed.json", store=OneLakeDocumentStore(tmp_path), ttl_seconds=60, clock=clock
    )
    cache.set("CVE-1", {"score": 1})

    clock.now += 59
    assert cache.get("CVE-1")[0] is True

    clock.now += 2
    assert cache.get("CVE-1") == (False, None)


def test_get_entry_exposes_age_for_per_value_ttls(tmp_path):
    clock = _Clock()
    cache = EnrichmentCache(
        "cache/feed.json", store=OneLakeDocumentStore(tmp_path), ttl_seconds=60, clock=clock
    )
    cache.set("CVE-1", {})
    clock.now += 100

    found, value, age = cache.get_entry("CVE-1")
    assert (found, value) == (True, {})
    assert age == pytest.approx(100)


def test_cache_survives_a_new_process(tmp_path):
    """The whole point of the OneLake tier: a fresh instance (a restarted
    replica) reads back what a previous one wrote."""
    EnrichmentCache("cache/feed.json", store=OneLakeDocumentStore(tmp_path)).set("CVE-1", {"score": 1})

    revived = EnrichmentCache("cache/feed.json", store=OneLakeDocumentStore(tmp_path))
    assert revived.get("CVE-1") == (True, {"score": 1})


def test_expired_entries_are_dropped_on_flush(tmp_path):
    """Otherwise the document grows without bound as CVE ids churn."""
    clock = _Clock()
    store = OneLakeDocumentStore(tmp_path)
    cache = EnrichmentCache("cache/feed.json", store=store, ttl_seconds=60, clock=clock)
    cache.set("old", {"score": 1})
    clock.now += 120
    cache.set("new", {"score": 2})

    assert set(store.read("cache/feed.json")["entries"]) == {"new"}


def test_without_a_store_the_cache_is_memory_only():
    cache = EnrichmentCache("cache/feed.json", store=None)
    cache.set("CVE-1", {"score": 1})
    assert cache.get("CVE-1") == (True, {"score": 1})


def test_store_failures_never_reach_the_caller(tmp_path):
    """A cache must degrade, not break the endpoint it accelerates."""

    class _BrokenStore:
        def read(self, name):
            raise RuntimeError("onelake unavailable")

        def put(self, name, payload):
            raise RuntimeError("onelake unavailable")

    cache = EnrichmentCache("cache/feed.json", store=_BrokenStore())
    cache.set("CVE-1", {"score": 1})
    assert cache.get("CVE-1") == (True, {"score": 1})
