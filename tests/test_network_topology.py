"""Tests for hub-spoke topology stitching across subscription connections."""

from __future__ import annotations

from network_scenario import (
    FIREWALL_ID,
    FIREWALL_SUBNET,
    HUB_VNET,
    PROD_VNET,
    UAT_VNET,
    network_rows,
)

from network import (
    NetworkIntelligenceService,
    NetworkScope,
    NetworkSnapshot,
    VNet,
    VNetPeering,
    build_service,
    build_topology,
    load_network_snapshot,
)
from network.models import PrivateEndpoint, PrivateLinkResource
from network.tightening import RuleFinding
from network.topology import HUB_SCORE_THRESHOLD, PEER_RESOLUTION_VALUES


def _topology():
    return build_topology(load_network_snapshot(network_rows()))


class TestRuleFindingAffectedResources:
    def test_nsg_findings_name_the_subnets_and_nics_the_control_protects(self) -> None:
        service = build_service(network_rows())
        finding = next(
            item
            for item in service.rule_findings
            if item.control == "nsg" and item.affected_resource_ids
        )
        nsg = next(
            item
            for item in service.snapshot.nsgs
            if item.resource_id == finding.control_id
        )

        assert finding.affected_resource_ids == tuple(
            sorted({*nsg.subnet_ids, *nsg.nic_ids})
        )

    def test_firewall_findings_name_the_network_the_collection_governs(self) -> None:
        service = build_service(network_rows())
        finding = next(
            item
            for item in service.rule_findings
            if item.control == "azure_firewall"
        )

        assert finding.affected_resource_ids
        assert any("/subnets/" in item for item in finding.affected_resource_ids)
        assert any(
            "/virtualnetworks/" in item and "/subnets/" not in item
            for item in finding.affected_resource_ids
        )

    def test_legacy_finding_payload_uses_an_empty_optional_collection(self) -> None:
        legacy = {
            "finding_id": "finding-1",
            "category": "any_any",
            "severity": "critical",
            "rule_id": "/rules/1",
            "rule_name": "allow-all",
            "control": "nsg",
            "control_id": "/nsgs/1",
            "title": "Broad rule",
            "detail": "Existing detail",
            "evidence": {"source": "*"},
            "recommendation": "Narrow the rule",
        }

        finding = RuleFinding(**legacy)

        assert finding.affected_resource_ids == ()
        assert {
            key: value
            for key, value in finding.to_dict().items()
            if key != "affected_resource_ids"
        } == {
            **legacy,
            "connection_id": "",
            "subscription_id": "",
            "environment": "",
        }


class TestHubClassification:
    def test_hub_is_identified_by_evidence(self) -> None:
        topology = _topology()
        assert [hub.vnet_id for hub in topology.hubs] == [HUB_VNET.casefold()]

    def test_hub_signals_are_reported_as_evidence(self) -> None:
        hub = _topology().hubs[0]
        assert "hosts_firewall" in hub.signals
        assert "hosts_vpn_gateway" in hub.signals
        assert hub.score >= HUB_SCORE_THRESHOLD

    def test_spokes_are_classified_as_spokes(self) -> None:
        topology = _topology()
        assert {spoke.vnet_id for spoke in topology.spokes} == {
            PROD_VNET.casefold(),
            UAT_VNET.casefold(),
        }

    def test_name_alone_does_not_make_a_hub(self) -> None:
        """A VNet called 'hub' with no hub services must not be classified as one."""
        rows = [
            {
                "entity_type": "VNet",
                "resource_id": "/subscriptions/s/vnets/vnet-hub-lookalike",
                "name": "vnet-hub-lookalike",
                "payload_json": '{"addressSpaces": ["10.9.0.0/16"]}',
            }
        ]
        topology = build_topology(load_network_snapshot(rows))
        assert topology.hubs == ()
        assert len(topology.isolated) == 1

    def test_vnet_with_no_peerings_is_isolated(self) -> None:
        rows = [
            {
                "entity_type": "VNet",
                "resource_id": "/subscriptions/s/vnets/lonely",
                "name": "lonely",
                "payload_json": "{}",
            }
        ]
        assert len(build_topology(load_network_snapshot(rows)).isolated) == 1


class TestPeeringStitching:
    def test_cross_subscription_peerings_are_detected(self) -> None:
        topology = _topology()
        cross = [link for link in topology.links if link.is_cross_subscription]
        assert cross, "hub and spokes live in different subscriptions"

    def test_hub_dependents_span_subscriptions(self) -> None:
        topology = _topology()
        peers = topology.peers_of(HUB_VNET.casefold())
        assert set(peers) == {PROD_VNET.casefold(), UAT_VNET.casefold()}

    def test_one_sided_peering_is_flagged_unhealthy(self) -> None:
        """PROD->UAT exists but UAT->PROD does not."""
        topology = _topology()
        unhealthy = [link for link in topology.links if not link.is_healthy]
        assert any(
            link.local_vnet_id == PROD_VNET.casefold()
            and link.remote_vnet_id == UAT_VNET.casefold()
            for link in unhealthy
        )

    def test_unobserved_remote_vnet_is_surfaced_not_dropped(self) -> None:
        rows = [
            {
                "entity_type": "VNet",
                "resource_id": "/subscriptions/a/vnets/local",
                "name": "local",
                "payload_json": "{}",
            },
            {
                "entity_type": "VNetPeering",
                "resource_id": "/subscriptions/a/vnets/local/peerings/p",
                "name": "p",
                "payload_json": (
                    '{"localVnetId": "/subscriptions/a/vnets/local",'
                    ' "remoteVnetId": "/subscriptions/zzz/vnets/notonboarded",'
                    ' "peeringState": "Connected"}'
                ),
            },
        ]
        topology = build_topology(load_network_snapshot(rows))
        assert "/subscriptions/zzz/vnets/notonboarded" in topology.unresolved_peer_vnet_ids
        link = topology.links[0]
        assert link.remote_vnet_observed is False

    def test_hub_for_resolves_a_spokes_hub(self) -> None:
        topology = _topology()
        assert topology.hub_for(PROD_VNET.casefold()) == HUB_VNET.casefold()


class TestPeerResolution:
    VNET_A = "/subscriptions/sub-a/resourceGroups/rg-a/providers/Microsoft.Network/virtualNetworks/a"
    VNET_B = "/subscriptions/sub-b/resourceGroups/rg-b/providers/Microsoft.Network/virtualNetworks/b"
    VNET_C = "/subscriptions/sub-c/resourceGroups/rg-c/providers/Microsoft.Network/virtualNetworks/c"

    @classmethod
    def _service(cls) -> NetworkIntelligenceService:
        vnet_a = VNet(
            resource_id=cls.VNET_A,
            name="a",
            subscription_id="sub-a",
            resource_group="rg-a",
        )
        vnet_b = VNet(
            resource_id=cls.VNET_B,
            name="b",
            subscription_id="sub-b",
            resource_group="rg-b",
        )
        peer_b = VNetPeering(
            resource_id=f"{cls.VNET_A}/virtualNetworkPeerings/to-b",
            name="to-b",
            subscription_id="sub-a",
            resource_group="rg-a",
            local_vnet_id=cls.VNET_A,
            remote_vnet_id=cls.VNET_B,
            peering_state="Connected",
        )
        peer_c = VNetPeering(
            resource_id=f"{cls.VNET_A}/virtualNetworkPeerings/to-c",
            name="to-c",
            subscription_id="sub-a",
            resource_group="rg-a",
            local_vnet_id=cls.VNET_A,
            remote_vnet_id=cls.VNET_C,
            peering_state="Connected",
        )
        return NetworkIntelligenceService(
            NetworkSnapshot(
                vnets=(vnet_a, vnet_b),
                peerings=(peer_b, peer_c),
            )
        )

    def test_scoped_topology_distinguishes_excluded_and_not_ingested_peers(
        self,
    ) -> None:
        payload = self._service().scoped(
            NetworkScope(subscription_ids=("sub-a",))
        ).topology.to_dict()

        assert payload["unresolved_peers"] == [
            {
                "vnet_id": self.VNET_B.casefold(),
                "peer_resolution": "excluded_by_scope",
            },
            {
                "vnet_id": self.VNET_C.casefold(),
                "peer_resolution": "not_ingested",
            },
        ]
        assert payload["unresolved_peer_vnet_ids"] == [
            self.VNET_B.casefold(),
            self.VNET_C.casefold(),
        ]

    def test_peer_resolution_values_are_closed(self) -> None:
        assert PEER_RESOLUTION_VALUES == frozenset(
            {"not_ingested", "excluded_by_scope", "observed"}
        )
        payload = self._service().scoped(
            NetworkScope(subscription_ids=("sub-a",))
        ).topology.to_dict()
        assert {
            item["peer_resolution"] for item in payload["unresolved_peers"]
        } <= PEER_RESOLUTION_VALUES

    def test_empty_scope_never_marks_peer_excluded(self) -> None:
        payload = self._service().scoped(NetworkScope()).topology.to_dict()

        assert all(
            item["peer_resolution"] != "excluded_by_scope"
            for item in payload["unresolved_peers"]
        )
        assert payload["unresolved_peer_vnet_ids"] == [self.VNET_C.casefold()]

    def test_widening_scope_restores_real_vnet_kind(self) -> None:
        payload = self._service().scoped(
            NetworkScope(subscription_ids=("sub-a", "sub-b"))
        ).topology.to_dict()

        assert self.VNET_B.casefold() not in {
            item["vnet_id"] for item in payload["unresolved_peers"]
        }
        by_id = {item["id"]: item for item in payload["resources"]}
        assert by_id[self.VNET_B.casefold()]["entity_type"] == "VNet"


class TestSharedServices:
    def test_hub_services_are_promoted(self) -> None:
        kinds = {service.service_kind for service in _topology().shared_services}
        assert "firewall" in kinds
        assert "vpn" in kinds

    def test_consumers_are_the_spokes(self) -> None:
        firewall = next(
            s for s in _topology().shared_services if s.service_kind == "firewall"
        )
        assert set(firewall.consumer_vnet_ids) == {PROD_VNET.casefold(), UAT_VNET.casefold()}


class TestConnectionScope:
    def test_topology_records_every_connection(self) -> None:
        assert set(_topology().connection_ids) == {"conn-hub", "conn-prod", "conn-uat"}

    def test_serializes_for_the_api(self) -> None:
        payload = _topology().to_dict()
        assert payload["hubs"]
        assert payload["links"]
        assert "shared_services" in payload
        assert payload["resources"]
        assert payload["relationships"]

    def test_serialized_topology_contains_resource_level_network_nodes(self) -> None:
        payload = _topology().to_dict()
        resource_types = {item["entity_type"] for item in payload["resources"]}
        assert {
            "VNet",
            "Subnet",
            "NetworkSecurityGroup",
            "NetworkSecurityRule",
            "RouteTable",
            "Route",
            "AzureFirewall",
            "FirewallPolicy",
            "FirewallRuleCollection",
            "FirewallRule",
        } <= resource_types

    def test_serialized_resource_nodes_embed_control_specific_details(self) -> None:
        payload = _topology().to_dict()
        firewall = next(item for item in payload["resources"] if item["entity_type"] == "AzureFirewall")
        nsg = next(item for item in payload["resources"] if item["entity_type"] == "NetworkSecurityGroup")
        route_table = next(item for item in payload["resources"] if item["entity_type"] == "RouteTable")
        assert firewall["details"]["rules"]
        assert nsg["details"]["rules"]
        assert route_table["details"]["routes"]


class TestPrivateLinkProjection:
    FABRIC_ID = (
        "/subscriptions/sub-a/resourceGroups/rg-data/providers/"
        "Microsoft.Fabric/capacities/fabric-capacity"
    )
    AI_ID = (
        "/subscriptions/sub-a/resourceGroups/rg-ai/providers/"
        "Microsoft.CognitiveServices/accounts/foundry-tools"
    )

    @classmethod
    def _resource(
        cls,
        resource_id: str,
        *,
        name: str,
        resource_type: str,
        service_kind: str,
        subscription_id: str = "sub-a",
    ) -> PrivateLinkResource:
        return PrivateLinkResource(
            resource_id=resource_id,
            name=name,
            subscription_id=subscription_id,
            resource_group="rg-private-link",
            connection_id=f"conn-{subscription_id}",
            service_kind=service_kind,
            resource_type=resource_type,
            public_network_access="Enabled",
        )

    def test_fabric_and_ai_resources_project_with_workload_types_and_details(self) -> None:
        snapshot = NetworkSnapshot(
            private_link_resources=(
                self._resource(
                    self.FABRIC_ID,
                    name="fabric-capacity",
                    resource_type="Microsoft.Fabric/capacities",
                    service_kind="Microsoft Fabric",
                ),
                self._resource(
                    self.AI_ID,
                    name="foundry-tools",
                    resource_type="Microsoft.CognitiveServices/accounts",
                    service_kind="Azure AI Services",
                ),
            )
        )

        resources = build_topology(snapshot).to_dict()["resources"]
        by_id = {resource["id"].casefold(): resource for resource in resources}

        assert len(resources) == 2
        assert by_id[self.FABRIC_ID.casefold()]["entity_type"] == "FabricCapacity"
        assert by_id[self.AI_ID.casefold()]["entity_type"] == "AIFoundryAccount"
        assert by_id[self.FABRIC_ID.casefold()]["details"] | {
            "service_kind": "Microsoft Fabric",
            "public_network_access": "Enabled",
            "private_link_candidate": True,
            "private_link_scope": "tenant_or_workspace",
        } == by_id[self.FABRIC_ID.casefold()]["details"]
        assert by_id[self.AI_ID.casefold()]["details"] | {
            "service_kind": "Azure AI Services",
            "public_network_access": "Enabled",
            "private_link_candidate": True,
        } == by_id[self.AI_ID.casefold()]["details"]

    def test_missing_private_endpoint_gap_ids_resolve_to_projected_nodes(self) -> None:
        service = NetworkIntelligenceService(
            NetworkSnapshot(
                private_link_resources=(
                    self._resource(
                        self.FABRIC_ID,
                        name="fabric-capacity",
                        resource_type="Microsoft.Fabric/capacities",
                        service_kind="Microsoft Fabric",
                    ),
                    self._resource(
                        self.AI_ID,
                        name="foundry-tools",
                        resource_type="Microsoft.CognitiveServices/accounts",
                        service_kind="Azure AI Services",
                    ),
                )
            )
        )

        node_ids = {
            resource["id"].casefold()
            for resource in service.topology.to_dict()["resources"]
        }
        gaps = [
            gap
            for gap in service.gaps
            if gap.category == "missing_private_endpoint"
        ]

        assert [gap.resource_id for gap in gaps] == [self.AI_ID.casefold()]
        assert all(gap.resource_id.casefold() in node_ids for gap in gaps)

    def test_private_link_resource_already_projected_as_workload_is_not_duplicated(
        self,
    ) -> None:
        target_id = self.AI_ID.swapcase()
        snapshot = NetworkSnapshot(
            private_endpoints=(
                PrivateEndpoint(
                    resource_id=(
                        "/subscriptions/sub-a/resourceGroups/rg-network/providers/"
                        "Microsoft.Network/privateEndpoints/ai-pe"
                    ),
                    name="ai-pe",
                    subscription_id="sub-a",
                    resource_group="rg-network",
                    target_resource_id=target_id,
                ),
            ),
            private_link_resources=(
                self._resource(
                    self.AI_ID,
                    name="foundry-tools",
                    resource_type="Microsoft.CognitiveServices/accounts",
                    service_kind="Azure AI Services",
                ),
            ),
        )

        matches = [
            resource
            for resource in build_topology(snapshot).to_dict()["resources"]
            if resource["id"].casefold() == self.AI_ID.casefold()
        ]

        assert len(matches) == 1
        assert matches[0]["entity_type"] == "AIFoundryAccount"
        assert matches[0]["details"]["private_link_candidate"] is True

    def test_summary_reports_exact_projected_full_node_count(self) -> None:
        endpoints = tuple(
            PrivateEndpoint(
                resource_id=(
                    "/subscriptions/sub-a/resourceGroups/rg-network/providers/"
                    f"Microsoft.Network/privateEndpoints/pe-{index}"
                ),
                name=f"pe-{index}",
                subscription_id="sub-a",
                resource_group="rg-network",
                target_resource_id=(
                    "/subscriptions/sub-a/resourceGroups/rg-app/providers/"
                    f"Microsoft.Web/sites/app-{index}"
                ),
            )
            for index in range(800)
        )
        analysis = NetworkIntelligenceService(
            NetworkSnapshot(private_endpoints=endpoints)
        ).analyze()
        summary_payload = analysis.summary()
        full_payload = analysis.topology.to_dict(detail="full")

        assert sum(analysis.topology.snapshot.counts().values()) == 800
        assert len(full_payload["resources"]) == 1_600
        assert (
            summary_payload["projected_full_node_count"]
            == len(full_payload["resources"])
        )

    def test_unrecognised_private_link_provider_uses_generic_type(self) -> None:
        resource_id = (
            "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Contoso.Widgets/widgets/widget-1"
        )
        snapshot = NetworkSnapshot(
            private_link_resources=(
                self._resource(
                    resource_id,
                    name="widget-1",
                    resource_type="Contoso.Widgets/widgets",
                    service_kind="Contoso Widgets",
                ),
            )
        )

        resources = build_topology(snapshot).to_dict()["resources"]

        assert len(resources) == 1
        assert resources[0]["entity_type"] == "PrivateLinkResource"

    def test_scoped_projection_excludes_out_of_scope_private_link_resources(
        self,
    ) -> None:
        foreign_id = self.AI_ID.replace("sub-a", "sub-b")
        service = NetworkIntelligenceService(
            NetworkSnapshot(
                private_link_resources=(
                    self._resource(
                        self.AI_ID,
                        name="foundry-tools-a",
                        resource_type="Microsoft.CognitiveServices/accounts",
                        service_kind="Azure AI Services",
                    ),
                    self._resource(
                        foreign_id,
                        name="foundry-tools-b",
                        resource_type="Microsoft.CognitiveServices/accounts",
                        service_kind="Azure AI Services",
                        subscription_id="sub-b",
                    ),
                )
            )
        )

        resources = service.scoped(
            NetworkScope(subscription_ids=("sub-a",))
        ).topology.to_dict()["resources"]

        assert [resource["id"] for resource in resources] == [self.AI_ID.casefold()]


class TestResourceTopologyProjection:

    def test_shared_service_summaries_do_not_duplicate_provider_resource_nodes(self) -> None:
        payload = _topology().to_dict()
        resource_types = [item["entity_type"] for item in payload["resources"]]
        assert "SharedService" not in resource_types
        firewall_ids = [item["id"] for item in payload["resources"] if item["entity_type"] == "AzureFirewall"]
        assert len(firewall_ids) == len(set(firewall_ids))

    def test_serialized_relationships_are_clickable_and_descriptive(self) -> None:
        payload = _topology().to_dict()
        relationships = {(item["relationship_type"], item["label"]) for item in payload["relationships"]}
        assert ("protected_by", "protected by NSG") in relationships
        assert ("has_rule", "has NSG rule") in relationships
        assert ("has_route", "has route") in relationships
        assert ("enforces_policy", "enforces policy") in relationships
        assert ("has_peering", "has peering") in relationships
        assert ("peers_with", "peers with VNet") in relationships

    def test_private_endpoint_and_shared_service_relationships_are_provider_backed(self) -> None:
        payload = _topology().to_dict()
        relationships = payload["relationships"]
        assert any(
            item["relationship_type"] == "attached_to"
            and item["label"] == "attached to subnet"
            and "/privateendpoints/" in item["source"]
            and "/subnets/" in item["target"]
            for item in relationships
        )

    def test_subnet_hosted_azure_services_have_reverse_attachment_edges(self) -> None:
        payload = _topology().to_dict()
        relationships = payload["relationships"]
        assert any(
            item["source"] == FIREWALL_ID.casefold()
            and item["target"] == FIREWALL_SUBNET.casefold()
            and item["relationship_type"] == "attached_to"
            and item["label"] == "attached to subnet"
            for item in relationships
        )
        bastion_vnet = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/demo-vnet"
        bastion_subnet = f"{bastion_vnet}/subnets/azurebastionsubnet"
        bastion_id = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/bastionhosts/demo-bastion"
        rows = [
            {
                "entity_type": "VNet",
                "resource_id": bastion_vnet,
                "name": "demo-vnet",
                "payload_json": {"subnetIds": [bastion_subnet]},
            },
            {
                "entity_type": "Subnet",
                "resource_id": bastion_subnet,
                "name": "AzureBastionSubnet",
                "payload_json": {"vnetId": bastion_vnet},
            },
            {
                "entity_type": "Bastion",
                "resource_id": bastion_id,
                "name": "demo-bastion",
                "payload_json": {"vnetId": bastion_vnet, "subnetId": bastion_subnet},
            },
        ]
        bastion_relationships = build_topology(load_network_snapshot(rows)).to_dict()["relationships"]
        assert any(
            item["source"] == bastion_id.casefold()
            and item["target"] == bastion_subnet.casefold()
            and item["relationship_type"] == "attached_to"
            for item in bastion_relationships
        )
        assert any(
            item["source"] == bastion_subnet.casefold()
            and item["target"] == bastion_id.casefold()
            and item["relationship_type"] == "hosts"
            for item in bastion_relationships
        )

    def test_subnet_hosted_services_are_not_also_hosted_by_the_vnet(self) -> None:
        """The subnet already sits inside the VNet, so the VNet edge is noise."""
        payload = _topology().to_dict()
        hosted_by_vnet = {
            (item["source"], item["target"])
            for item in payload["relationships"]
            if item["relationship_type"] == "hosts" and item["source"] == HUB_VNET.casefold()
        }
        assert (HUB_VNET.casefold(), FIREWALL_ID.casefold()) not in hosted_by_vnet
        assert any(
            item["source"] == FIREWALL_SUBNET.casefold()
            and item["target"] == FIREWALL_ID.casefold()
            and item["relationship_type"] == "hosts"
            for item in payload["relationships"]
        )

    def test_virtual_appliance_route_links_to_the_firewall_it_targets(self) -> None:
        """A next hop IP is only useful once it resolves to the real appliance."""
        vnet = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/rt-vnet"
        subnet = f"{vnet}/subnets/azurefirewallsubnet"
        firewall = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/azurefirewalls/fw"
        table = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/routetables/rt"
        route = f"{table}/routes/to-firewall"
        rows = [
            {"entity_type": "VNet", "resource_id": vnet, "name": "rt-vnet", "payload_json": {"subnetIds": [subnet]}},
            {"entity_type": "Subnet", "resource_id": subnet, "name": "AzureFirewallSubnet", "payload_json": {"vnetId": vnet}},
            {
                "entity_type": "AzureFirewall",
                "resource_id": firewall,
                "name": "fw",
                "payload_json": {"vnetId": vnet, "subnetId": subnet, "privateIp": "10.0.2.4"},
            },
            {"entity_type": "RouteTable", "resource_id": table, "name": "rt", "payload_json": {}},
            {
                "entity_type": "Route",
                "resource_id": route,
                "name": "to-firewall",
                "payload_json": {
                    "routeTableId": table,
                    "addressPrefix": "0.0.0.0/0",
                    "nextHopType": "VirtualAppliance",
                    "nextHopIp": "10.0.2.4",
                },
            },
        ]
        topology = build_topology(load_network_snapshot(rows))
        relationships = topology.to_dict()["relationships"]
        assert any(
            item["source"] == route.casefold()
            and item["target"] == firewall.casefold()
            and item["relationship_type"] == "next_hop"
            for item in relationships
        )

        summary = topology.to_dict(detail="summary")
        assert route.casefold() not in {
            item["id"] for item in summary["resources"]
        }
        assert any(
            item["source"] == table.casefold()
            and item["target"] == firewall.casefold()
            and item["relationship_type"] == "next_hop"
            for item in summary["relationships"]
        )

    def test_nic_and_private_endpoint_link_to_the_workloads_they_serve(self) -> None:
        """A NIC that serves nothing and an endpoint with no service are dead ends."""
        vnet = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/w-vnet"
        subnet = f"{vnet}/subnets/default"
        nic = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/networkinterfaces/vm1-nic"
        vm = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1"
        endpoint = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/privateendpoints/pe"
        cosmos = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.documentdb/databaseaccounts/cosmos"
        rows = [
            {"entity_type": "VNet", "resource_id": vnet, "name": "w-vnet", "payload_json": {"subnetIds": [subnet]}},
            {"entity_type": "Subnet", "resource_id": subnet, "name": "default", "payload_json": {"vnetId": vnet}},
            {
                "entity_type": "NetworkInterface",
                "resource_id": nic,
                "name": "vm1-nic",
                "payload_json": {"subnetId": subnet, "attachedResourceId": vm},
            },
            {
                "entity_type": "PrivateEndpoint",
                "resource_id": endpoint,
                "name": "pe",
                "payload_json": {"subnetId": subnet, "targetResourceId": cosmos},
            },
        ]
        payload = build_topology(load_network_snapshot(rows)).to_dict()
        assert {vm.casefold(), cosmos.casefold()} <= {item["id"] for item in payload["resources"]}
        assert any(
            item["source"] == nic.casefold()
            and item["target"] == vm.casefold()
            and item["relationship_type"] == "attached_to"
            for item in payload["relationships"]
        )
        assert any(
            item["source"] == endpoint.casefold()
            and item["target"] == cosmos.casefold()
            and item["relationship_type"] == "connects_to"
            for item in payload["relationships"]
        )
        # The ARM type is what lets the canvas pick the real service glyph, so a
        # workload must not fall back to the generic bucket when it is known.
        by_id = {item["id"]: item for item in payload["resources"]}
        assert by_id[vm.casefold()]["entity_type"] == "VirtualMachine"
        assert by_id[cosmos.casefold()]["entity_type"] == "CosmosDb"

    def test_unrecognised_workload_still_becomes_a_node(self) -> None:
        """An unmapped ARM type must not drop the endpoint's target entirely."""
        vnet = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/u-vnet"
        subnet = f"{vnet}/subnets/default"
        endpoint = "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/privateendpoints/pe"
        target = "/subscriptions/sub-a/resourcegroups/rg/providers/contoso.widgets/widgets/w1"
        rows = [
            {"entity_type": "VNet", "resource_id": vnet, "name": "u-vnet", "payload_json": {"subnetIds": [subnet]}},
            {"entity_type": "Subnet", "resource_id": subnet, "name": "default", "payload_json": {"vnetId": vnet}},
            {
                "entity_type": "PrivateEndpoint",
                "resource_id": endpoint,
                "name": "pe",
                "payload_json": {"subnetId": subnet, "targetResourceId": target},
            },
        ]
        payload = build_topology(load_network_snapshot(rows)).to_dict()
        by_id = {item["id"]: item for item in payload["resources"]}
        assert by_id[target.casefold()]["entity_type"] == "AttachedWorkload"

    def test_container_apps_internal_lb_links_to_its_backend_subnet_and_environment(self) -> None:
        """The ACA internal LB has IP-only backends and a tag-only owner, not ARM refs.

        Without the subnet/tag fallback this node has no edges and is a dead
        end on the canvas; with it, the LB attaches to the subnet its AKS-style
        backend members live in and to the Container Apps environment that
        owns it.
        """
        vnet = "/subscriptions/sub-a/resourcegroups/me_env_rg/providers/microsoft.network/virtualnetworks/v"
        subnet = f"{vnet}/subnets/legion"
        env = "/subscriptions/sub-a/resourcegroups/app-rg/providers/microsoft.app/managedenvironments/cae"
        lb = "/subscriptions/sub-a/resourcegroups/me_env_rg/providers/microsoft.network/loadbalancers/capp-svc-lb"
        rows = [
            {"entity_type": "VNet", "resource_id": vnet, "name": "v", "payload_json": {"subnetIds": [subnet]}},
            {"entity_type": "Subnet", "resource_id": subnet, "name": "legion", "payload_json": {"vnetId": vnet}},
            {
                "entity_type": "LoadBalancer",
                "resource_id": lb,
                "name": "capp-svc-lb",
                "payload_json": {
                    "subnetId": "",
                    "vnetId": "",
                    "backendResourceIds": [],
                    "tags": {"aca-managed-env-id": env},
                    "properties": {
                        "backendAddressPools": [
                            {
                                "properties": {
                                    "loadBalancerBackendAddresses": [
                                        {"properties": {"subnet": {"id": subnet}}}
                                    ]
                                }
                            }
                        ]
                    },
                },
            },
        ]
        payload = build_topology(load_network_snapshot(rows)).to_dict()
        by_id = {item["id"]: item for item in payload["resources"]}
        assert env.casefold() in by_id
        assert by_id[env.casefold()]["entity_type"] == "ContainerAppEnvironment"
        assert any(
            item["source"] == lb.casefold()
            and item["target"] == subnet.casefold()
            and item["relationship_type"] == "load_balances"
            for item in payload["relationships"]
        )
        assert any(
            item["source"] == env.casefold()
            and item["target"] == lb.casefold()
            and item["relationship_type"] == "hosts"
            for item in payload["relationships"]
        )

    def test_load_balancers_with_the_same_name_are_disambiguated(self) -> None:
        """Azure lets unrelated LBs across resource groups share a name; the canvas must not."""
        lb_a = "/subscriptions/sub-a/resourcegroups/rg-one/providers/microsoft.network/loadbalancers/capp-svc-lb"
        lb_b = "/subscriptions/sub-a/resourcegroups/rg-two/providers/microsoft.network/loadbalancers/capp-svc-lb"
        rows = [
            {
                "entity_type": "LoadBalancer",
                "resource_id": lb_a,
                "name": "capp-svc-lb",
                "resource_group": "rg-one",
                "payload_json": {},
            },
            {
                "entity_type": "LoadBalancer",
                "resource_id": lb_b,
                "name": "capp-svc-lb",
                "resource_group": "rg-two",
                "payload_json": {},
            },
        ]
        payload = build_topology(load_network_snapshot(rows)).to_dict()
        by_id = {item["id"]: item for item in payload["resources"]}
        assert by_id[lb_a.casefold()]["name"] != by_id[lb_b.casefold()]["name"]
        assert "rg-one" in by_id[lb_a.casefold()]["name"]
        assert "rg-two" in by_id[lb_b.casefold()]["name"]

    def test_private_dns_zone_is_linked_to_a_vnet_only_once(self) -> None:
        """A zone that both links to and serves a VNet must not draw two edges."""
        payload = _topology().to_dict()
        pairs = [
            (item["source"], item["target"])
            for item in payload["relationships"]
            if item["relationship_type"] in {"linked_to", "serves"}
        ]
        assert len(pairs) == len(set(pairs))

    def test_vnet_peering_resources_are_connected_to_vnets(self) -> None:
        payload = _topology().to_dict()
        relationships = payload["relationships"]
        peering_edges = [item for item in relationships if item["relationship_type"] in {"has_peering", "peers_with"}]
        assert any(item["source"] == HUB_VNET.casefold() and item["relationship_type"] == "has_peering" for item in peering_edges)
        assert any(item["target"] == PROD_VNET.casefold() and item["relationship_type"] == "peers_with" for item in peering_edges)
        assert any(
            item["relationship_type"] == "serves"
            and item["details"]["provider_resource_id"] == item["source"]
            and item["target"].endswith("/virtualnetworks/vnet-prod")
            for item in relationships
        )


class TestHubDependents:
    def test_answers_what_depends_on_the_hub(self) -> None:
        service = build_service(network_rows())
        result = service.hub_dependents(HUB_VNET)
        assert result["dependent_count"] == 2
        assert {item["name"] for item in result["dependent_vnets"]} == {
            "vnet-prod",
            "vnet-uat",
        }
        assert result["shared_services"]

    def test_dependents_carry_business_context(self) -> None:
        result = build_service(network_rows()).hub_dependents(HUB_VNET)
        prod = next(x for x in result["dependent_vnets"] if x["name"] == "vnet-prod")
        assert prod["business_service"] == "Payments"
        assert prod["environment"] == "prod"
