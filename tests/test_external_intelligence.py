from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fabric.schema_registry import schema_for
from intelligence.vulnerability.enrichment_cache import EnrichmentCache
from intelligence.vulnerability.enrichment_worker import (
    EnrichmentTarget,
    EnrichmentWorker,
)
from intelligence.vulnerability.models import CVE, SecurityUpdate
from storage.onelake_documents import OneLakeDocumentStore


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 6, 4, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **values: float) -> None:
        self.now += timedelta(**values)


class _Msrc:
    def __init__(self, *, title: str = "Security update") -> None:
        self.title = title
        self.calls: list[tuple[str, ...]] = []

    def fetch(self, identifiers: tuple[str, ...]) -> tuple[SecurityUpdate, ...]:
        self.calls.append(identifiers)
        return tuple(
            SecurityUpdate(
                update_id=identifier,
                kb_id=identifier,
                title=self.title,
                cve_ids=("CVE-2026-0001",),
                published_at="2026-09-01",
            )
            for identifier in identifiers
        )


class _Nvd:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_ids: set[str] = set()

    def fetch_cves(self, identifiers: tuple[str, ...]) -> tuple[CVE, ...]:
        self.calls.append(identifiers)
        if any(identifier in self.fail_ids for identifier in identifiers):
            raise RuntimeError("provider body with token=do-not-persist")
        return tuple(
            CVE(
                cve_id=identifier,
                description=f"Details for {identifier}",
                severity="HIGH",
            )
            for identifier in identifiers
        )


class _Epss:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.payload: dict[str, object] = {
            "epss_score": 0.91,
            "epss_percentile": 0.97,
            "source_at": "2026-09-05",
        }

    def fetch_scores(self, identifiers: tuple[str, ...]) -> dict[str, dict[str, object]]:
        self.calls.append(identifiers)
        return {identifier: dict(self.payload) for identifier in identifiers}


class _Kev:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_catalog(self) -> dict[str, dict[str, str]]:
        self.calls += 1
        return {
            "CVE-2026-0001": {
                "kev_date_added": "2026-09-02",
                "kev_due_date": "2026-09-23",
                "kev_ransomware_use": "Known",
            },
            "CVE-2026-0002": {
                "kev_date_added": "2026-09-03",
                "kev_due_date": "2026-09-24",
                "kev_ransomware_use": "Unknown",
            },
        }


def _worker(
    tmp_path,
    clock: _Clock,
    *,
    document: str = "enrichment/items.json",
    msrc: _Msrc | None = None,
    nvd: _Nvd | None = None,
    epss: _Epss | None = None,
    kev: _Kev | None = None,
    max_items: int = 20,
) -> tuple[EnrichmentWorker, EnrichmentCache]:
    cache = EnrichmentCache(
        document,
        store=OneLakeDocumentStore(tmp_path),
    )
    worker = EnrichmentWorker(
        cache,
        msrc_connector=msrc or _Msrc(),
        nvd_connector=nvd or _Nvd(),
        epss_connector=epss or _Epss(),
        kev_connector=kev or _Kev(),
        clock=clock,
        refresh_interval_seconds=60,
        failure_retry_seconds=10,
        max_items=max_items,
    )
    return worker, cache


def test_worker_refreshes_all_four_feeds_as_independent_items(tmp_path) -> None:
    clock = _Clock()
    kev = _Kev()
    worker, cache = _worker(tmp_path, clock, kev=kev)

    outcomes = worker.refresh(
        (
            EnrichmentTarget("msrc", " kb5000001 "),
            EnrichmentTarget("nvd", "cve-2026-0001"),
            EnrichmentTarget("epss", "cve-2026-0001"),
            EnrichmentTarget("kev", "cve-2026-0001"),
            EnrichmentTarget("kev", "cve-2026-0002"),
        )
    )

    assert [outcome.status for outcome in outcomes] == ["succeeded"] * 5
    assert kev.calls == 1
    assert cache.get_record("msrc", "KB5000001")["payload"]["cve_ids"] == [
        "CVE-2026-0001"
    ]
    assert cache.get_record("nvd", "CVE-2026-0001")["payload"]["severity"] == "HIGH"
    assert cache.get_record("epss", "CVE-2026-0001")["payload"]["epss_score"] == 0.91
    assert (
        cache.get_record("kev", "CVE-2026-0001")["payload"]["kev_ransomware_use"]
        == "Known"
    )
    assert {record["source"] for record in cache.records()} == {
        "msrc",
        "nvd",
        "epss",
        "kev",
    }


def test_mixed_failure_retains_only_failed_items_lkg_and_original_generation(
    tmp_path,
) -> None:
    clock = _Clock()
    nvd = _Nvd()
    epss = _Epss()
    worker, cache = _worker(tmp_path, clock, nvd=nvd, epss=epss)
    targets = (
        EnrichmentTarget("nvd", "CVE-2026-0001"),
        EnrichmentTarget("epss", "CVE-2026-0001"),
    )

    worker.refresh(targets)
    previous = cache.get_record("nvd", "CVE-2026-0001")
    clock.advance(seconds=61)
    nvd.fail_ids.add("CVE-2026-0001")
    epss.payload["epss_score"] = 0.95

    outcomes = worker.refresh(targets)
    failed = cache.get_record("nvd", "CVE-2026-0001")
    succeeded = cache.get_record("epss", "CVE-2026-0001")

    assert [outcome.status for outcome in outcomes] == ["failed", "succeeded"]
    assert failed["payload"] == previous["payload"]
    assert failed["provenance_hash"] == previous["provenance_hash"]
    assert failed["succeeded_at"] == previous["succeeded_at"]
    assert failed["source_at"] == previous["source_at"]
    assert failed["enriched_at"] == previous["enriched_at"]
    assert failed["attempted_at"] != previous["attempted_at"]
    assert failed["safe_error_code"] == "provider_unavailable"
    assert failed["stale"] is True
    assert succeeded["payload"]["epss_score"] == 0.95
    assert succeeded["status"] == "succeeded"
    assert succeeded["stale"] is False
    assert "do-not-persist" not in json.dumps(cache.records())


def test_records_and_failed_lkg_survive_restart(tmp_path) -> None:
    clock = _Clock()
    nvd = _Nvd()
    worker, cache = _worker(tmp_path, clock, nvd=nvd)
    target = EnrichmentTarget("nvd", "CVE-2026-0001")
    worker.refresh((target,))
    clock.advance(seconds=61)
    nvd.fail_ids.add("CVE-2026-0001")
    worker.refresh((target,))
    before = cache.get_record("nvd", "CVE-2026-0001")

    restarted = EnrichmentCache(
        "enrichment/items.json",
        store=OneLakeDocumentStore(tmp_path),
    )

    assert restarted.get_record("nvd", "cve-2026-0001", now=clock.now) == before


def test_refresh_after_boundary_is_due_and_stale_not_early(tmp_path) -> None:
    clock = _Clock()
    nvd = _Nvd()
    worker, cache = _worker(tmp_path, clock, nvd=nvd)
    target = EnrichmentTarget("nvd", "CVE-2026-0001")
    worker.refresh((target,))

    clock.advance(seconds=59)
    assert cache.get_record("nvd", target.identifier, now=clock.now)["stale"] is False
    assert worker.refresh((target,))[0].status == "not_due"
    assert len(nvd.calls) == 1

    clock.advance(seconds=1)
    assert cache.get_record("nvd", target.identifier, now=clock.now)["stale"] is True
    assert worker.refresh((target,))[0].status == "succeeded"
    assert len(nvd.calls) == 2


@pytest.mark.parametrize(
    "unsafe_payload",
    (
        {"epss_score": 0.5, "description": "<script>alert(1)</script>"},
        {"epss_score": 0.5, "description": "safe\x00control"},
        {"epss_score": 0.5, "authorization": "Bearer provider-secret"},
        {"epss_score": 0.5, "description": "x" * 9_000},
    ),
)
def test_active_control_and_unbounded_content_is_rejected_before_persistence(
    tmp_path,
    unsafe_payload,
) -> None:
    clock = _Clock()
    epss = _Epss()
    epss.payload = unsafe_payload
    worker, cache = _worker(tmp_path, clock, epss=epss)

    outcome = worker.refresh((EnrichmentTarget("epss", "CVE-2026-0001"),))[0]
    record = cache.get_record("epss", "CVE-2026-0001")
    stored = OneLakeDocumentStore(tmp_path).read("enrichment/items.json")

    assert outcome.status == "failed"
    assert record["payload"] is None
    assert record["safe_error_code"] in {
        "unsafe_content",
        "provider_control_content",
        "payload_too_large",
    }
    assert "provider-secret" not in json.dumps(stored)
    assert "<script>" not in json.dumps(stored)


def test_provenance_and_request_hashes_are_deterministic_and_content_bound(
    tmp_path,
) -> None:
    clock = _Clock()
    epss = _Epss()
    worker, cache = _worker(tmp_path, clock, epss=epss)
    target = EnrichmentTarget("epss", "CVE-2026-0001")
    worker.refresh((target,))
    first = cache.get_record("epss", target.identifier)

    clock.advance(seconds=61)
    worker.refresh((target,))
    same = cache.get_record("epss", target.identifier)
    assert same["request_hash"] == first["request_hash"]
    assert same["provenance_hash"] == first["provenance_hash"]
    assert len(same["request_hash"]) == 64
    assert len(same["provenance_hash"]) == 64

    epss.payload["epss_score"] = 0.99
    clock.advance(seconds=61)
    worker.refresh((target,))
    changed = cache.get_record("epss", target.identifier)
    assert changed["request_hash"] == first["request_hash"]
    assert changed["provenance_hash"] != first["provenance_hash"]


def test_worker_enforces_a_total_item_bound_before_calling_providers(tmp_path) -> None:
    clock = _Clock()
    nvd = _Nvd()
    worker, cache = _worker(tmp_path, clock, nvd=nvd, max_items=2)

    outcomes = worker.refresh(
        (
            EnrichmentTarget("nvd", "CVE-2026-0001"),
            EnrichmentTarget("nvd", "CVE-2026-0002"),
            EnrichmentTarget("nvd", "CVE-2026-0003"),
        )
    )

    assert len(outcomes) == 2
    assert len(nvd.calls) == 2
    assert cache.get_record("nvd", "CVE-2026-0003") is None


def test_enrichment_schema_is_additive_and_preserves_remediation_role_identity() -> None:
    enrichment = schema_for("silver_exposure_enrichment")
    approval = schema_for("silver_remediation_approval_policies")

    assert {
        "enrichment_key",
        "source",
        "identifier",
        "payload_json",
        "payload_version",
        "provenance_hash",
        "request_hash",
        "attempted_at",
        "succeeded_at",
        "source_at",
        "enriched_at",
        "refresh_after",
        "status",
        "stale",
        "safe_error_code",
    } <= set(enrichment.names)
    assert approval.field("role_ids_json").nullable is True
