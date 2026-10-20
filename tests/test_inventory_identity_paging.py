"""Inventory identity consumers must capture all authorized rows exactly once."""

from __future__ import annotations

import pytest

from api.scope import Scope
from intelligence.inventory.read_port import InventoryReadPort
from intelligence.inventory.service import InventoryService
from onboarding.config import ConnectorConfig
from onboarding.ingestion_service import IngestionService
from onboarding.inventory_read_adapter import InventoryReadAdapter

SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})


def _service(count: int) -> InventoryService:
    return InventoryService({
        "generation_id": "generation-a",
        "resource_observations": [
            {
                "resource_id": f"/subscriptions/{subscription}/resource-{index:06d}",
                "resource_name": f"resource-{index:06d}",
                "subscription_id": subscription,
                "family": "paas",
                "resource_type": "microsoft.web/sites",
                "observed_at": "2026-10-16T01:16:10Z",
                "ingestion_run_id": "source-run",
                "query_version": "resource-observation-v1",
                "provider_payload_json": f'{{"nested":{{"sequence":{index}}}}}',
            }
            for subscription, size in (("sub-a", count), ("sub-b", 1))
            for index in range(size)
        ],
    })


@pytest.mark.parametrize("consumer", ["adapter", "ingestion"])
@pytest.mark.parametrize("count", [0, 1, 10_001, 100_000])
def test_real_identity_consumers_capture_exact_authorized_total_in_one_scan(
    tmp_path, monkeypatch, consumer, count,
):
    service = _service(count)
    port = InventoryReadPort(service)
    original = service.resources
    calls = []

    def resources(scope, **kwargs):
        calls.append((scope, kwargs))
        return original(scope, **kwargs)

    monkeypatch.setattr(service, "resources", resources)
    if consumer == "adapter":
        result = InventoryReadAdapter(port).resources(SCOPE)
        ids = [row["resource_id"] for row in result]
    else:
        ingestion = IngestionService(
            ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a",)),
            inventory_read_port=port,
        )
        result = ingestion._identity_rows_from_inventory(["sub-a"])["resources"]
        ids = [row["id"] for row in result]
    assert len(result) == count
    assert set(ids) == {f"/subscriptions/sub-a/resource-{index:06d}" for index in range(count)}
    if count:
        assert result[-1]["properties"] == {"nested": {"sequence": count - 1}}
    expected = [(SCOPE, {"offset": 0, "limit": None})]
    if consumer == "ingestion":
        expected.append((SCOPE, {"limit": None}))  # Existing containment projection.
    assert calls == expected


@pytest.mark.parametrize("fault,message", [
    ("total", "exact total"),
    ("short", "incomplete"),
    ("duplicate", "duplicate identity"),
    ("missing", "missing or duplicate identity"),
])
def test_identity_snapshot_rejects_incomplete_or_ambiguous_results(fault, message):
    class BrokenPort:
        def list_resources(self, scope, *, limit):
            assert scope == SCOPE
            assert limit is None
            page = {"total": 2, "resources": [{"resource_id": "a"}, {"resource_id": "b"}]}
            if fault == "total":
                page.pop("total")
            elif fault == "short":
                page["resources"].pop()
            elif fault == "duplicate":
                page["resources"][1] = {"resource_id": "A"}
            elif fault == "missing":
                page["resources"][0] = {"resource_id": ""}
            return page

    with pytest.raises(RuntimeError, match=message):
        InventoryReadAdapter(BrokenPort()).resources(SCOPE)
