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
from storage.onelake_documents import DocumentSnapshot, OneLakeDocumentStore


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


def test_scheduled_factory_reads_pointer_and_cache_from_aiops_home(
    tmp_path,
    monkeypatch,
) -> None:
    from scripts import refresh_exposure_enrichment as cli

    root = tmp_path / "aiops"
    OneLakeDocumentStore(root).write(
        "exposure/gold-generation-pointer.json",
        {"readable_generation_id": "generation-7", "revision": 1},
        expected_revision=0,
    )
    monkeypatch.setenv("AIOPS_HOME", str(root))
    monkeypatch.setenv("AIOPS_CONNECTION_HOME", str(root / "connections"))
    monkeypatch.setattr(cli, "_build_table_reader", lambda _root: lambda *_args: ())

    service = cli._build_prefetch_service(max_items=1)

    assert service.discovery.discover().generation_id == "generation-7"
    assert service.discovery.pointer_store.root == str(root)
    assert service.checkpoint_store.root == str(root)
    assert OneLakeDocumentStore(root / "connections").read(
        "exposure/gold-generation-pointer.json"
    ) == {}


@pytest.mark.parametrize("change", ["generation", "revision", "deleted", "etag_only"])
def test_discovery_rejects_pointer_change_before_any_worker_activity(
    tmp_path, change,
) -> None:
    from unittest.mock import Mock

    pointer = {"readable_generation_id": "generation-7", "revision": 1}
    after = dict(pointer)
    if change == "generation":
        after["readable_generation_id"] = "generation-8"
    elif change == "revision":
        after["revision"] = 2
    elif change == "deleted":
        after = {}
    store = Mock(spec=OneLakeDocumentStore)
    store.read.return_value = pointer
    store.read_snapshot.side_effect = [
        DocumentSnapshot(pointer, "etag-1"),
        DocumentSnapshot(after, None if change == "deleted" else "etag-2"),
    ]
    reads = []

    def read(table, _columns):
        reads.append(table)
        return ({"cve_id": "CVE-2026-9001"},) if table == "silver_defender_findings" else ()

    service, cache, _nvd, events = _service(tmp_path, _Clock())
    service.discovery = ExposureGenerationDiscovery(pointer_store=store, table_reader=read)
    with pytest.raises(RuntimeError, match="exposure_generation_changed_during_discovery"):
        service.run()
    assert len(reads) == len(ExposureGenerationDiscovery._TABLE_COLUMNS)
    assert events == []
    assert cache.records() == ()
    assert store.read_snapshot.call_count == 2


@pytest.mark.parametrize("fail_on", [1, 2])
def test_discovery_propagates_strict_pointer_read_errors(tmp_path, fail_on) -> None:
    from unittest.mock import Mock

    pointer = {"readable_generation_id": "generation-7", "revision": 1}
    store = Mock(spec=OneLakeDocumentStore)
    store.read.return_value = pointer
    error = OSError("private-pointer-store-error")
    store.read_snapshot.side_effect = (
        [error] if fail_on == 1 else [DocumentSnapshot(pointer, "etag-1"), error]
    )
    reads = []
    discovery = ExposureGenerationDiscovery(
        pointer_store=store, table_reader=lambda *args: reads.append(args) or (),
    )
    with pytest.raises(OSError, match="private-pointer-store-error"):
        discovery.discover()
    assert len(reads) == (0 if fail_on == 1 else len(discovery._TABLE_COLUMNS))


def test_discovery_accepts_unchanged_snapshot_and_rejects_missing_pointer(tmp_path) -> None:
    store = OneLakeDocumentStore(tmp_path)
    reads = []
    discovery = ExposureGenerationDiscovery(
        pointer_store=store, table_reader=lambda *args: reads.append(args) or (),
    )
    with pytest.raises(LookupError, match="exposure_generation_unavailable"):
        discovery.discover()
    assert reads == []
    store.write(
        "exposure/gold-generation-pointer.json",
        {"readable_generation_id": "generation-7", "revision": 1},
        expected_revision=0,
    )
    assert discovery.discover().generation_id == "generation-7"


@pytest.mark.parametrize("mutation", ["publish", "corrupt"])
def test_cli_fails_closed_when_real_pointer_changes_during_table_reads(
    tmp_path, mutation,
) -> None:
    from scripts.refresh_exposure_enrichment import main

    service, cache, _nvd, events = _service(tmp_path / "cache", _Clock())
    store = OneLakeDocumentStore(tmp_path / "publisher")
    document = "exposure/gold-generation-pointer.json"
    store.write(
        document, {"readable_generation_id": "generation-7", "revision": 1},
        expected_revision=0,
    )
    reads = []

    def read(table, _columns):
        reads.append(table)
        if len(reads) == 1:
            if mutation == "publish":
                store.write(
                    document,
                    {"readable_generation_id": "generation-8", "revision": 2},
                    expected_revision=1,
                )
            else:
                (tmp_path / "publisher" / document).write_text("private-invalid-json")
        return ()

    service.discovery = ExposureGenerationDiscovery(pointer_store=store, table_reader=read)
    output = io.StringIO()
    code = main(
        ["--prefetch-generation"],
        prefetch_factory=lambda **_: service,
        stdout=output,
    )
    report = json.loads(output.getvalue())
    assert code == (2 if mutation == "corrupt" else 1)
    assert report["status"] == "failed"
    assert report["failure_stage"] == "prefetch_run"
    assert report["outcomes"] == []
    assert "private-invalid-json" not in output.getvalue()
    assert "generation-8" not in output.getvalue()
    assert cache.records() == ()
    assert events == []


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


@pytest.mark.parametrize("kb_ids,cve_ids", [
    (("KB5030001",), ()),
    ((), ("CVE-2026-9001",)),
])
@pytest.mark.parametrize("provider_fails", [False, True])
def test_cli_retains_completed_outcomes_when_cursor_write_fails(
    tmp_path, monkeypatch, kb_ids, cve_ids, provider_fails,
) -> None:
    from scripts.refresh_exposure_enrichment import main

    service, cache, nvd, _events = _service(
        tmp_path, _Clock(), kb_ids=kb_ids, cve_ids=cve_ids, max_items=3,
    )
    nvd.fail = provider_fails

    def fail_cursor(*_args, **_kwargs):
        raise OSError("private-checkpoint-response")

    monkeypatch.setattr(service, "_save_cursor", fail_cursor)
    output = io.StringIO()
    assert main(
        ["--prefetch-generation", "--max-items", "3"],
        prefetch_factory=lambda **_: service,
        stdout=output,
    ) == 1

    report = json.loads(output.getvalue())
    expected_sources = ["msrc"] if kb_ids else ["nvd", "epss", "kev"]
    assert [row["source"] for row in report["outcomes"]] == expected_sources
    for row in report["outcomes"]:
        expected = "failed" if provider_fails and row["source"] == "nvd" else "succeeded"
        assert row["status"] == expected
    assert len(cache.records()) == len(expected_sources)
    assert report["status"] == "failed"
    assert report["failure_stage"] == "prefetch_run"
    assert report["error_category"] == "os_error"
    assert "private-checkpoint-response" not in output.getvalue()
    assert "secret provider payload" not in output.getvalue()
    for row in report["outcomes"]:
        assert set(row) == {
            "source", "identifier", "status", "attempted_at",
            "succeeded_at", "stale", "safe_error_code",
        }


def test_prefetch_callback_matches_success_report_without_duplicates(tmp_path) -> None:
    service, _cache, _nvd, _events = _service(
        tmp_path, _Clock(), kb_ids=("KB5030001",), max_items=4,
    )
    outcomes = []
    report = service.run(on_outcome=outcomes.append)
    assert [outcome.to_dict() for outcome in outcomes] == list(report.outcomes)
    assert len(outcomes) == 4


def test_prefetch_callback_failure_propagates_without_advancing_cursor(tmp_path) -> None:
    service, cache, _nvd, _events = _service(
        tmp_path, _Clock(), kb_ids=("KB5030001",), max_items=4,
    )

    def fail_callback(_outcome):
        raise RuntimeError("callback-unavailable")

    with pytest.raises(RuntimeError, match="callback-unavailable"):
        service.run(on_outcome=fail_callback)

    assert cache.get_record("msrc", "KB5030001") is not None
    assert "prefetch" not in service.checkpoint_store.read(service.checkpoint_document)


def test_cli_retains_first_outcome_when_later_item_persistence_fails(
    tmp_path, monkeypatch,
) -> None:
    from scripts.refresh_exposure_enrichment import main

    service, cache, _nvd, _events = _service(
        tmp_path, _Clock(), cve_ids=("CVE-2026-9001",), max_items=3,
    )
    checkpoint_success = cache.checkpoint_success
    calls = 0

    def fail_second_checkpoint(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private-cache-write-response")
        return checkpoint_success(**kwargs)

    monkeypatch.setattr(cache, "checkpoint_success", fail_second_checkpoint)
    output = io.StringIO()
    assert main(
        ["--prefetch-generation", "--max-items", "3"],
        prefetch_factory=lambda **_: service,
        stdout=output,
    ) == 1
    report = json.loads(output.getvalue())
    assert report["status"] == "failed"
    assert [(row["source"], row["status"]) for row in report["outcomes"]] == [
        ("nvd", "succeeded"),
    ]
    assert cache.get_record("nvd", "CVE-2026-9001") is not None
    assert cache.get_record("epss", "CVE-2026-9001") is None
    assert "prefetch" not in service.checkpoint_store.read(service.checkpoint_document)
    assert "private-cache-write-response" not in output.getvalue()


def test_cli_success_keeps_single_copy_of_streamed_prefetch_outcomes(tmp_path) -> None:
    from scripts.refresh_exposure_enrichment import main

    service, _cache, _nvd, _events = _service(
        tmp_path, _Clock(), kb_ids=("KB5030001",), max_items=4,
    )
    output = io.StringIO()
    assert main(
        ["--prefetch-generation", "--max-items", "4"],
        prefetch_factory=lambda **_: service,
        stdout=output,
    ) == 0
    report = json.loads(output.getvalue())
    assert report["status"] == "succeeded"
    assert report["selected_count"] == len(report["outcomes"]) == 4
    assert len({(row["source"], row["identifier"]) for row in report["outcomes"]}) == 4
    assert "failure_stage" not in report


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
        def run(self, *, on_outcome=None) -> _Report:
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
