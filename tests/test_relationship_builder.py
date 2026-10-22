from __future__ import annotations

import json

import pytest
from test_entity_builder import resource

from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder


@pytest.mark.parametrize("field", ["registryResourceId", "registry_resource_id"])
def test_exposure_registry_relationship_uses_explicit_bound_registry(field):
    registry_id = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.containerregistry/registries/acr"
    exposure_id = f"{registry_id}/images/sha256:abc"
    sources = [
        resource(
            resource_id=registry_id,
            entity_type="ContainerRegistry",
            resource_type="microsoft.containerregistry/registries",
            payload_json="{}",
        ),
        resource(
            resource_id=exposure_id,
            entity_type="ContainerImageExposure",
            resource_type="microsoft.containerregistry/registries/images",
            payload_json=json.dumps({field: registry_id.upper()}),
        ),
    ]
    entities = EntityBuilder().build(sources, "run-1")
    relationships = RelationshipBuilder().build(entities, "run-1")
    edges = [row for row in relationships if row["predicate"] == "exposes"]
    assert len(edges) == 1
    edge = edges[0]
    assert (edge["subject_id"], edge["subject_type"]) == (
        exposure_id, "ContainerImageExposure",
    )
    assert (edge["object_id"], edge["object_type"]) == (
        registry_id, "ContainerRegistry",
    )
    repeated = RelationshipBuilder().build(list(reversed(entities)), "run-2")
    replay = next(row for row in repeated if row["predicate"] == "exposes")
    assert replay["resource_id"] == edge["resource_id"]
    assert replay["change_version"] == edge["change_version"]


@pytest.mark.parametrize("binding,registry_type,include_registry", [
    ("", "ContainerRegistry", True),
    (None, "ContainerRegistry", True),
    ("/missing", "ContainerRegistry", True),
    ("bound", "Resource", True),
    ("bound", "ContainerRegistry", False),
])
def test_exposure_registry_relationship_never_infers_missing_binding(
    binding, registry_type, include_registry,
):
    registry_id = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.containerregistry/registries/acr"
    payload = {
        "targetResourceId": registry_id,
        "registryHost": "acr.azurecr.io",
        "registryResourceId": registry_id if binding == "bound" else binding,
    }
    sources = [
        resource(
            resource_id=f"{registry_id}/images/sha256:abc",
            entity_type="ContainerImageExposure",
            resource_type="microsoft.containerregistry/registries/images",
            payload_json=json.dumps(payload),
        ),
    ]
    if include_registry:
        sources.append(resource(
            resource_id=registry_id, entity_type=registry_type,
            resource_type="unknown", payload_json="{}",
        ))
    entities = EntityBuilder().build(sources, "run-1")
    assert not [
        row for row in RelationshipBuilder().build(entities, "run-1")
        if row["predicate"] == "exposes"
    ]


def test_relationship_builder_discovers_structural_and_tag_relationships():
    entities = EntityBuilder().build([resource()], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    triples = {
        (row["subject_type"], row["predicate"], row["object_type"])
        for row in relationships
    }

    assert ("Tenant", "owns", "Subscription") in triples
    assert ("Subscription", "contains", "ResourceGroup") in triples
    assert ("ResourceGroup", "contains", "VirtualMachine") in triples
    assert ("VirtualMachine", "member_of", "Application") in triples
    assert ("Application", "hosted_on", "VirtualMachine") in triples
    assert ("SupportTeam", "supports", "Application") in triples
    assert ("Owner", "owns", "Service") in triples
    assert ("BusinessService", "contains", "Application") in triples


def test_relationships_are_stable_and_deduplicated():
    entities = EntityBuilder().build([resource(), resource()], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    ids = [row["resource_id"] for row in relationships]

    assert len(ids) == len(set(ids))
    assert RelationshipBuilder().build(entities, "run-3")[0]["resource_id"] == relationships[0]["resource_id"]


def test_defender_vulnerability_finding_links_to_source_assessment():
    assessment_id = (
        "/subscriptions/sub-1/providers/microsoft.security/assessments/va-machines"
    )
    finding_id = f"{assessment_id}/subassessments/finding-1"
    entities = EntityBuilder().build(
        [
            resource(
                resource_id=assessment_id,
                entity_type="DefenderAssessment",
                resource_type="microsoft.security/assessments",
                payload_json=json.dumps({"targetResourceId": resource()["resource_id"]}),
            ),
            resource(
                resource_id=finding_id,
                entity_type="DefenderVulnerabilityFinding",
                resource_type="microsoft.security/assessments/subassessments",
                payload_json=json.dumps(
                    {
                        "targetResourceId": resource()["resource_id"],
                        "assessmentId": assessment_id,
                    }
                ),
            ),
            resource(),
        ],
        "run-defender",
    )

    relationships = RelationshipBuilder().build(entities, "run-defender")

    assert any(
        row["subject_id"] == finding_id
        and row["predicate"] == "derivedFrom"
        and row["object_id"] == assessment_id
        for row in relationships
    )


def test_application_dependencies_are_discovered_from_dependency_tags():
    row = resource()
    row["payload_json"] = row["payload_json"].replace(
        '"AppName": "Payments API",',
        '"AppName": "Payments API", "DependsOn": "Identity API, Ledger API",',
    )
    entities = EntityBuilder().build([row], "run-2")

    relationships = RelationshipBuilder().build(entities, "run-2")
    dependencies = [row for row in relationships if row["predicate"] == "depends_on"]

    assert {
        next(e["name"] for e in entities if e["resource_id"] == rel["object_id"])
        for rel in dependencies
    } == {"Identity API", "Ledger API"}


def test_container_apps_load_balancer_relationships_are_discovered_from_metadata():
    subnet_id = "/subscriptions/sub-1/resourceGroups/net/providers/Microsoft.Network/virtualNetworks/v/subnets/aca"
    environment_id = "/subscriptions/sub-1/resourceGroups/apps/providers/Microsoft.App/managedEnvironments/cae"
    load_balancer_id = "/subscriptions/sub-1/resourceGroups/net/providers/Microsoft.Network/loadBalancers/capp-svc-lb"
    entities = EntityBuilder().build(
        [
            resource(
                resource_id=subnet_id,
                entity_type="Subnet",
                resource_type="microsoft.network/subnets",
                name="aca",
                payload_json='{"vnetId":"/subscriptions/sub-1/resourceGroups/net/providers/Microsoft.Network/virtualNetworks/v"}',
            ),
            resource(
                resource_id=environment_id,
                entity_type="Resource",
                resource_type="microsoft.app/managedenvironments",
                name="cae",
                payload_json="{}",
            ),
            resource(
                resource_id=load_balancer_id,
                entity_type="LoadBalancer",
                resource_type="microsoft.network/loadbalancers",
                name="capp-svc-lb",
                payload_json=(
                    '{"tags":{"aca-managed-env-id":"'
                    + environment_id
                    + '"},"properties":{"backendAddressPools":[{"properties":'
                    '{"loadBalancerBackendAddresses":[{"properties":{"subnet":{"id":"'
                    + subnet_id
                    + '"}}}]}}]}}'
                ),
            ),
        ],
        "run-aca",
    )

    relationships = RelationshipBuilder().build(entities, "run-aca")

    assert any(
        row["subject_id"] == load_balancer_id.casefold()
        and row["predicate"] == "loadBalances"
        and row["object_id"] == subnet_id.casefold()
        for row in relationships
    )
    assert any(
        row["subject_id"] == environment_id.casefold()
        and row["predicate"] == "hosts"
        and row["object_id"] == load_balancer_id.casefold()
        for row in relationships
    )


def test_management_group_hierarchy_is_discovered():
    management_group = resource(
        resource_id="/providers/microsoft.management/managementgroups/mg-root",
        entity_type="ManagementGroup",
        resource_type="microsoft.management/managementgroups",
        name="mg-root",
        payload_json=(
            '{"id":"/providers/microsoft.management/managementgroups/mg-root",'
            '"name":"mg-root","tenantId":"tenant-1"}'
        ),
    )
    subscription = resource(
        resource_id="/subscriptions/sub-1",
        entity_type="Subscription",
        resource_type="microsoft.resources/subscriptions",
        name="sub-1",
        payload_json=(
            '{"id":"/subscriptions/sub-1","name":"sub-1","tenantId":"tenant-1",'
            '"subscriptionId":"sub-1","managementGroupAncestorsChain":[{"name":"mg-root"}]}'
        ),
    )
    entities = EntityBuilder().build([management_group, subscription], "run-2")

    relationships = RelationshipBuilder().build(entities, "run-2")

    assert any(
        row["subject_type"] == "ManagementGroup"
        and row["predicate"] == "contains"
        and row["object_type"] == "Subscription"
        for row in relationships
    )


def test_normalize_tag_value_treats_hyphen_underscore_space_as_equivalent():
    from ontology.relationship_builder import _normalize_tag_value

    assert _normalize_tag_value("Order-Service") == _normalize_tag_value("order_service")
    assert _normalize_tag_value("Order Service") == _normalize_tag_value("order-service")
    assert _normalize_tag_value("  Order   Service  ") == _normalize_tag_value("order_service")


def test_fuzzy_tag_value_links_asset_to_same_application_entity():
    hyphenated_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        name="vm1",
    )
    underscored_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=resource()["payload_json"].replace("Payments API", "Payments_API").replace(
            '"id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"',
            '"id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"',
        ).replace('"name": "vm1"', '"name": "vm2"'),
    )

    entities = EntityBuilder().build([hyphenated_vm, underscored_vm], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    member_of_applications = {
        row["object_id"]
        for row in relationships
        if row["subject_type"] == "VirtualMachine" and row["predicate"] == "member_of"
    }

    assert len(member_of_applications) == 1


def test_resource_group_level_tag_is_inherited_by_untagged_sibling():
    tagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        name="vm1",
    )
    payload = json.loads(tagged_vm["payload_json"])
    untagged_payload = dict(payload)
    untagged_payload["id"] = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"
    untagged_payload["name"] = "vm2"
    untagged_payload["tags"] = {"Environment": "Production"}
    untagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=json.dumps(untagged_payload),
    )

    entities = EntityBuilder().build([tagged_vm, untagged_vm], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    untagged_entity_id = next(
        entity["resource_id"]
        for entity in entities
        if entity["entity_type"] == "VirtualMachine" and entity["name"] == "vm2"
    )
    assert any(
        row["subject_id"] == untagged_entity_id and row["predicate"] == "member_of"
        for row in relationships
    )


def test_subscription_level_tag_is_inherited_across_resource_groups():
    tagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg-a/providers/microsoft.compute/virtualmachines/vm1",
        name="vm1",
    )
    payload = json.loads(tagged_vm["payload_json"])
    untagged_payload = dict(payload)
    untagged_payload["id"] = (
        "/subscriptions/sub-1/resourceGroups/rg-b/providers/Microsoft.Compute/virtualMachines/vm2"
    )
    untagged_payload["resourceGroup"] = "rg-b"
    untagged_payload["name"] = "vm2"
    untagged_payload["tags"] = {}
    untagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg-b/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=json.dumps(untagged_payload),
    )

    entities = EntityBuilder().build([tagged_vm, untagged_vm], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    untagged_entity_id = next(
        entity["resource_id"]
        for entity in entities
        if entity["entity_type"] == "VirtualMachine" and entity["name"] == "vm2"
    )
    assert any(
        row["subject_id"] == untagged_entity_id and row["predicate"] == "member_of"
        for row in relationships
    )


def test_resource_level_tag_takes_priority_over_inherited_tag():
    tagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        name="vm1",
    )
    payload = json.loads(tagged_vm["payload_json"])
    own_tagged_payload = dict(payload)
    own_tagged_payload["id"] = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"
    own_tagged_payload["name"] = "vm2"
    own_tagged_payload["tags"] = {"AppName": "Ledger API"}
    own_tagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=json.dumps(own_tagged_payload),
    )

    entities = EntityBuilder().build([tagged_vm, own_tagged_vm], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    own_tagged_entity_id = next(
        entity["resource_id"]
        for entity in entities
        if entity["entity_type"] == "VirtualMachine" and entity["name"] == "vm2"
    )
    ledger_application_id = next(
        entity["resource_id"]
        for entity in entities
        if entity["entity_type"] == "Application" and entity["name"] == "Ledger API"
    )
    payments_application_id = next(
        entity["resource_id"]
        for entity in entities
        if entity["entity_type"] == "Application" and entity["name"] == "Payments API"
    )

    member_of_object_ids = {
        row["object_id"]
        for row in relationships
        if row["subject_id"] == own_tagged_entity_id and row["predicate"] == "member_of"
    }
    assert member_of_object_ids == {ledger_application_id}
    assert payments_application_id not in member_of_object_ids


def test_application_inheritance_is_deterministic_and_skips_ambiguous_scope():
    payments_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/payments",
        name="payments",
    )
    base_payload = json.loads(payments_vm["payload_json"])
    payments_payload = dict(base_payload)
    payments_payload["id"] = payments_vm["resource_id"]
    payments_payload["name"] = "payments"
    payments_vm["payload_json"] = json.dumps(payments_payload)

    ledger_payload = dict(base_payload)
    ledger_payload["id"] = (
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/"
        "virtualMachines/ledger"
    )
    ledger_payload["name"] = "ledger"
    ledger_payload["tags"] = {"AppName": "Ledger API"}
    ledger_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/ledger",
        name="ledger",
        payload_json=json.dumps(ledger_payload),
    )

    untagged_payload = dict(base_payload)
    untagged_payload["id"] = (
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/"
        "virtualMachines/untagged"
    )
    untagged_payload["name"] = "untagged"
    untagged_payload["tags"] = {}
    untagged_vm = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/untagged",
        name="untagged",
        payload_json=json.dumps(untagged_payload),
    )

    results = []
    for source_rows in (
        [payments_vm, ledger_vm, untagged_vm],
        [untagged_vm, ledger_vm, payments_vm],
    ):
        entities = EntityBuilder().build(source_rows, "run-ambiguous")
        relationships = RelationshipBuilder().build(
            entities, "run-ambiguous"
        )
        untagged_id = next(
            entity["resource_id"]
            for entity in entities
            if entity["entity_type"] == "VirtualMachine"
            and entity["name"] == "untagged"
        )
        results.append(
            {
                row["object_id"]
                for row in relationships
                if row["subject_id"] == untagged_id
                and row["predicate"] == "member_of"
            }
        )

    assert results == [set(), set()]
