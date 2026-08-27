"""Unit tests for the P1 EPSS/KEV enrichment wiring in `src/api/runtime.py`:

- `_resolve_epss_scores` fetches and TTL-caches EPSS scores via
  `EpssScoreConnector`, falling back to a default (unexploited-looking) score
  on any connector failure without raising.
- `_resolve_kev_catalog` fetches and TTL-caches the full CISA KEV catalog via
  `KevCatalogConnector`, similarly degrading gracefully on failure.
"""

from __future__ import annotations

from api import runtime


def test_resolve_epss_scores_fetches_and_caches(monkeypatch):
    calls: list[tuple[str, ...]] = []

    class _FakeConnector:
        def fetch_scores(self, cve_ids):
            calls.append(cve_ids)
            return {"CVE-2024-1": {"epss_score": 0.9, "epss_percentile": 0.95}}

    monkeypatch.setattr(runtime, "EpssScoreConnector", _FakeConnector)
    runtime._enrichment_cache_for.cache_clear()

    first = runtime._resolve_epss_scores(("CVE-2024-1",))
    assert first["CVE-2024-1"]["epss_score"] == 0.9

    # Second call within the TTL should hit the cache, not the connector again.
    second = runtime._resolve_epss_scores(("CVE-2024-1",))
    assert second["CVE-2024-1"]["epss_score"] == 0.9
    assert len(calls) == 1


def test_resolve_epss_scores_defaults_on_connector_failure(monkeypatch):
    class _FailingConnector:
        def fetch_scores(self, cve_ids):
            raise RuntimeError("network down")

    monkeypatch.setattr(runtime, "EpssScoreConnector", _FailingConnector)
    runtime._enrichment_cache_for.cache_clear()

    scores = runtime._resolve_epss_scores(("CVE-2024-2",))
    assert scores["CVE-2024-2"] == {"epss_score": 0.0, "epss_percentile": 0.0}


def test_resolve_kev_catalog_fetches_and_caches(monkeypatch):
    calls = {"count": 0}

    class _FakeConnector:
        def fetch_catalog(self):
            calls["count"] += 1
            return {"CVE-2024-3": {"kev_date_added": "2024-01-01", "kev_due_date": "2024-01-15", "kev_ransomware_use": "Known"}}

    monkeypatch.setattr(runtime, "KevCatalogConnector", _FakeConnector)
    runtime._enrichment_cache_for.cache_clear()

    first = runtime._resolve_kev_catalog()
    assert first["CVE-2024-3"]["kev_ransomware_use"] == "Known"

    second = runtime._resolve_kev_catalog()
    assert second == first
    assert calls["count"] == 1


def test_resolve_kev_catalog_returns_empty_on_failure(monkeypatch):
    class _FailingConnector:
        def fetch_catalog(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(runtime, "KevCatalogConnector", _FailingConnector)
    runtime._enrichment_cache_for.cache_clear()

    assert runtime._resolve_kev_catalog() == {}
