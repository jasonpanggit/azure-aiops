from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.scope import Scope
from operations.page_context import PageSnapshot, deterministic_network_findings


def snapshot(**overrides):
    value = {
        "page_kind": "network",
        "page_id": "topology",
        "question": "What should I review?",
        "scope": {"declared": {"subscription": ["sub-1"]}},
        "selected_resources": [{
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/hub",
            "resource_type": "Microsoft.Network/virtualNetworks",
            "attributes": {"subscription": "sub-1"},
        }],
        "evidence": [{
            "evidence_id": "nsg-1",
            "section": "nsg",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/hub",
            "data": {"finding": "Inbound any-source rule", "compliant": False},
        }],
    }
    value.update(overrides)
    return PageSnapshot.model_validate(value)


def test_snapshot_is_strict_and_hashable():
    page = snapshot()
    assert len(page.snapshot_hash()) == 64
    with pytest.raises(ValidationError):
        PageSnapshot.model_validate({**page.model_dump(), "version": "99"})
    with pytest.raises(ValidationError):
        PageSnapshot.model_validate({**page.model_dump(), "unexpected": True})


def test_scope_and_evidence_references_are_validated():
    page = snapshot(rechecks=["nsg-1"])
    page.validate_effective_scope(Scope.from_mapping({"subscription": ["sub-1"]}))
    with pytest.raises(ValueError, match="wider"):
        page.validate_effective_scope(Scope.from_mapping({"subscription": ["sub-2"]}))
    with pytest.raises(ValidationError, match="named evidence"):
        snapshot(rechecks=["missing"])


def test_scope_validation_derives_id_only_resource_attributes_and_checks_evidence():
    page = snapshot(
        selected_resources=[{
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/hub",
            "resource_type": "Microsoft.Network/virtualNetworks",
        }],
        evidence=[{
            "evidence_id": "nsg-1",
            "section": "nsg",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/hub",
            "data": {"finding": "Inbound any-source rule", "compliant": False},
        }],
    )
    page.validate_effective_scope(Scope.from_mapping({"subscription": ["sub-1"]}))

    out_of_scope = page.model_copy(deep=True)
    out_of_scope.evidence[0].resource_id = (
        "/subscriptions/sub-2/resourceGroups/rg/providers/"
        "Microsoft.Network/networkSecurityGroups/hub"
    )
    with pytest.raises(ValueError, match="evidence resource"):
        out_of_scope.validate_effective_scope(
            Scope.from_mapping({"subscription": ["sub-1"]})
        )


def test_scope_validation_rejects_unverifiable_resource_ids():
    page = snapshot(
        selected_resources=[{
            "resource_id": "not-an-azure-resource-id",
            "resource_type": "Microsoft.Network/virtualNetworks",
        }]
    )
    with pytest.raises(ValueError, match="canonical resource ID"):
        page.validate_effective_scope(Scope.unrestricted())


def test_network_findings_are_deterministic_and_cited():
    findings = deterministic_network_findings(snapshot().model_copy(deep=True))
    assert findings[0]["check_id"] == "NET-NSG-001"
    assert findings[0]["evidence_refs"] == ["nsg-1"]
    assert findings[0]["actionable"] is True
    assert findings[0]["next_check"]
