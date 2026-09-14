from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from intelligence.vulnerability.enrichment_cache import EnrichmentCache
from intelligence.vulnerability.enrichment_worker import EnrichmentWorker
from intelligence.vulnerability.exposure_prefetch import (
    ExposureGenerationDiscovery,
    ExposureIdentifierSet,
    ExposurePrefetchService,
    extract_canonical_exposure_ids,
)
from intelligence.vulnerability.models import CVE, SecurityUpdate
from storage.onelake_documents import OneLakeDocumentStore


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class _Discovery:
    def __init__(self, *, kb_ids: tuple[str, ...] = (), cve_ids: tuple[str, ...] = ()):
        self.identifiers = ExposureIdentifierSet("generation-7", kb_ids, cve_ids)

    def discover(self) -> ExposureIdentifierSet:
        return self.identifiers


class _Msrc:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def fetch(self, identifiers: tuple[str, ...]) -> tuple[SecurityUpdate, ...]:
        self.events.extend(f"msrc:{identifier}" for identifier in identifiers)
        return tuple(
            SecurityUpdate(
                update_id=identifier,
                kb_id=identifier,
                title="Update",
                cve_ids=("CVE-2026-9001",),
                published_at="2026-09-01",
            )
            for identifier in identifiers
        )


class _Nvd:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail = False

    def fetch_item(self, identifier: str) -> tuple[CVE, str]:
        self.events.append(f"nvd:{identifier}")
        if self.fail:
            raise RuntimeError("secret provider payload")
        return (
            CVE(
                cve_id=identifier,
                description=f"Details for {identifier}",
                severity="HIGH",
            ),
            "2026-09-10",
        )


class _Epss:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def fetch_scores(
        self,
        identifiers: tuple[str, ...],
    ) -> dict[str, dict[str, float]]:
        self.events.extend(f"epss:{identifier}" for identifier in identifiers)
        return {identifier: {"epss_score": 0.8} for identifier in identifiers}


class _Kev:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def fetch_catalog(self) -> dict[str, dict[str, str]]:
        self.events.append("kev:catalog")
        return {
            "CVE-2026-9001": {"kev_date_added": "2026-09-01"},
            "CVE-2026-9002": {"kev_date_added": "2026-09-02"},
        }


def _service(
    tmp_path,
    clock: _Clock,
    *,
    kb_ids: tuple[str, ...] = (),
    cve_ids: tuple[str, ...] = (),
    max_items: int = 20,
) -> tuple[ExposurePrefetchService, EnrichmentCache, _Nvd, list[str]]:
    events: list[str] = []
    store = OneLakeDocumentStore(tmp_path)
    cache = EnrichmentCache(
        "enrichment/items.json",
        store=store,
        clock=lambda: clock.now.timestamp(),
    )
    nvd = _Nvd(events)
    worker = EnrichmentWorker(
        cache,
        msrc_connector=_Msrc(events),
        nvd_connector=nvd,
        epss_connector=_Epss(events),
        kev_connector=_Kev(events),
        clock=clock,
        refresh_interval_seconds=60,
        failure_retry_seconds=10,
        max_items=max_items,
    )
    return (
        ExposurePrefetchService(
            discovery=_Discovery(kb_ids=kb_ids, cve_ids=cve_ids),
            worker=worker,
            checkpoint_store=store,
            max_items=max_items,
            clock=clock,
        ),
        cache,
        nvd,
        events,
    )


def test_extracts_stable_canonical_ids_from_published_and_source_tables() -> None:
    identifiers = extract_canonical_exposure_ids(
        {
            "gold_exposure_facts": (
                {
                    "read_model_generation_id": "generation-7",
                    "active": True,
                    "weakness_kind": "kb",
                    "weakness_id": " kb5030002 ",
                },
                {
                    "read_model_generation_id": "old",
                    "active": True,
                    "weakness_kind": "cve",
                    "weakness_id": "CVE-2026-9999",
                },
                {
                    "read_model_generation_id": "generation-7",
                    "active": True,
                    "weakness_kind": "cve",
                    "weakness_id": "cve-2026-0002",
                },
            ),
            "silver_patch_findings": (
                {"kb_id": "5030001"},
                {"kb_id": "not-a-kb"},
            ),
            "silver_defender_findings": (
                {"cve_id": "CVE-2026-0001"},
                {"cve_id": "cve-2026-0002"},
            ),
            "silver_container_image_exposure": (
                {"cve_ids": ["CVE-2026-0003", "CVE-2026-0001"]},
            ),
        },
        generation_id="generation-7",
    )

    assert identifiers.kb_ids == ("KB5030001", "KB5030002")
    assert identifiers.cve_ids == (
        "CVE-2026-0001",
        "CVE-2026-0002",
        "CVE-2026-0003",
    )


def test_discovery_reads_pointer_and_enforces_explicit_bounds(tmp_path) -> None:
    store = OneLakeDocumentStore(tmp_path)
    store.write(
        "exposure/gold-generation-pointer.json",
        {"readable_generation_id": "generation-7", "revision": 1},
        expected_revision=0,
    )

    def read(table: str, _columns: tuple[str, ...]):
        if table == "silver_defender_findings":
            return ({"cve_id": "CVE-2026-0001"}, {"cve_id": "CVE-2026-0002"})
        return ()

    discovery = ExposureGenerationDiscovery(
        pointer_store=store,
        table_reader=read,
        max_identifiers=1,
    )

    with pytest.raises(ValueError, match="identifier_bound"):
        discovery.discover()

    row_bounded = ExposureGenerationDiscovery(
        pointer_store=store,
        table_reader=read,
        max_rows_per_table=1,
    )
    with pytest.raises(ValueError, match="source_row_bound"):
        row_bounded.discover()


def test_prefetch_checkpoints_msrc_then_expands_durable_kb_cves(tmp_path) -> None:
    clock = _Clock()
    service, cache, _nvd, events = _service(
        tmp_path,
        clock,
        kb_ids=("KB5030001",),
        cve_ids=("CVE-2026-9002",),
        max_items=4,
    )

    report = service.run()

    assert report.status == "succeeded"
    assert report.selected_count == 4
    assert report.direct_cve_count == 1
    assert report.expanded_cve_count == 2
    assert events[0] == "msrc:5030001"
    assert cache.get_record("msrc", "KB5030001")["payload"]["cve_ids"] == [
        "CVE-2026-9001"
    ]
    assert cache.get_record("nvd", "CVE-2026-9001") is not None
    assert cache.get_record("epss", "CVE-2026-9001") is not None
    assert cache.get_record("kev", "CVE-2026-9001") is not None


def test_prefetch_skips_not_due_leaders_and_caps_missing_targets(tmp_path) -> None:
    clock = _Clock()
    service, cache, _nvd, _events = _service(
        tmp_path,
        clock,
        cve_ids=("CVE-2026-9001", "CVE-2026-9002"),
        max_items=3,
    )
    first = service.run()
    assert first.selected_count == 3

    second = service.run()

    assert second.selected_count == 3
    assert {row["identifier"] for row in second.outcomes} == {"CVE-2026-9002"}
    assert {row["source"] for row in second.outcomes} == {"nvd", "epss", "kev"}
    assert len(cache.records(now=clock.now)) == 6


def test_prefetch_prioritizes_later_missing_targets_before_earlier_due_lkg(
    tmp_path,
) -> None:
    clock = _Clock()
    initial, _cache, _nvd, _events = _service(
        tmp_path,
        clock,
        cve_ids=("CVE-2026-9001",),
        max_items=3,
    )
    assert initial.run().selected_count == 3
    clock.advance(seconds=61)
    service, _cache, _nvd, _events = _service(
        tmp_path,
        clock,
        cve_ids=("CVE-2026-9001", "CVE-2026-9002"),
        max_items=1,
    )

    report = service.run()

    assert [(row["source"], row["identifier"]) for row in report.outcomes] == [
        ("nvd", "CVE-2026-9002")
    ]


def test_persisted_cursor_advances_past_a_due_failed_target(tmp_path) -> None:
    clock = _Clock()
    service, _cache, nvd, _events = _service(
        tmp_path,
        clock,
        cve_ids=("CVE-2026-9001", "CVE-2026-9002"),
        max_items=1,
    )
    nvd.fail = True

    first = service.run()
    clock.advance(seconds=11)
    second = service.run()

    assert [(row["source"], row["identifier"]) for row in first.outcomes] == [
        ("nvd", "CVE-2026-9001")
    ]
    assert [(row["source"], row["identifier"]) for row in second.outcomes] == [
        ("epss", "CVE-2026-9001")
    ]
    documents = sorted(
        str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*.json")
    )
    assert documents == ["enrichment/items.json"]
    stored = OneLakeDocumentStore(tmp_path).read("enrichment/items.json")
    assert stored["prefetch"]["cve_cursor"].startswith("CVE-2026-9001|")


def test_partial_provider_failure_preserves_lkg_and_sanitizes_report(tmp_path) -> None:
    clock = _Clock()
    service, cache, nvd, _events = _service(
        tmp_path,
        clock,
        cve_ids=("CVE-2026-9001",),
        max_items=3,
    )
    service.run()
    previous = cache.get_record("nvd", "CVE-2026-9001", now=clock.now)
    clock.advance(seconds=61)
    nvd.fail = True

    report = service.run()
    failed = cache.get_record("nvd", "CVE-2026-9001", now=clock.now)
    serialized = json.dumps(report.to_dict())

    assert report.status == "partial"
    assert report.failed_count == 1
    assert failed["payload"] == previous["payload"]
    assert failed["provenance_hash"] == previous["provenance_hash"]
    assert failed["safe_error_code"] == "provider_unavailable"
    assert "secret provider payload" not in serialized
    assert set(report.outcomes[0]) == {
        "source",
        "identifier",
        "status",
        "attempted_at",
        "succeeded_at",
        "stale",
        "safe_error_code",
    }


def test_cli_generation_prefetch_emits_bounded_safe_report() -> None:
    from scripts.refresh_exposure_enrichment import main

    calls: list[int] = []

    class _Report:
        def to_dict(self) -> dict[str, Any]:
            return {
                "status": "partial",
                "generation_id": "generation-7",
                "selected_count": 2,
                "attempted_count": 2,
                "failed_count": 1,
                "outcomes": [
                    {
                        "source": "nvd",
                        "identifier": "CVE-2026-9001",
                        "status": "failed",
                        "attempted_at": "2026-09-14T12:00:00Z",
                        "succeeded_at": None,
                        "stale": True,
                        "safe_error_code": "provider_unavailable",
                    }
                ],
            }

    class _Service:
        def run(self) -> _Report:
            return _Report()

    output = io.StringIO()
    result = main(
        ["--prefetch-generation", "--max-items", "2"],
        prefetch_factory=lambda *, max_items: calls.append(max_items) or _Service(),
        stdout=output,
    )

    assert result == 0
    assert calls == [2]
    assert json.loads(output.getvalue())["status"] == "partial"
    assert "provider payload" not in output.getvalue()
