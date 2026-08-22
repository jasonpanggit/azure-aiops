from __future__ import annotations

from typing import Any

from network.flow import FlowHop, FlowQuery, FlowResult


class BlastRadiusEngine:
    """Builds bounded business and dependency blast-radius projections."""

    def __init__(self, *, max_items: int = 50, network_lookup: Any | None = None) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("Blast-radius item bound must be a positive integer")
        self.max_items = max_items
        self.network_lookup = network_lookup

    def analyze(self, finding):
        applications = sorted(set(finding.get("impacted_applications") or []))[: self.max_items]
        services = sorted(set(finding.get("impacted_services") or []))[: self.max_items]
        business_services = sorted(set(finding.get("impacted_business_services") or []))[: self.max_items]
        owner = str(finding.get("owner") or "Unknown")
        support = str(finding.get("support_team") or "Unknown")
        downstream = (finding.get("downstream_dependents") or [])[: self.max_items]
        dependency_tree = {
            "root": finding.get("resource"),
            "applications": applications,
            "services": services,
            "business_services": business_services,
            "upstream": (finding.get("upstream_dependencies") or [])[: self.max_items],
            "downstream": downstream,
        }
        network = self._network_context(finding)
        return {
            "applications": applications,
            "services": services,
            "business_services": business_services,
            "business_functions": (finding.get("business_functions") or [])[: self.max_items],
            "owners": [] if owner.casefold() == "unknown" else [owner],
            "support_teams": [] if support.casefold() == "unknown" else [support],
            "dependency_tree": dependency_tree,
            "subscriptions": network["subscriptions"],
            "network_paths": network["network_paths"],
            "hub_dependencies": network["hub_dependencies"],
            "firewall_impact": network["firewall_impact"],
            "nsg_impact": network["nsg_impact"],
            "downstream_services": downstream,
            "notes": network["notes"],
            "application_count": len(applications),
            "service_count": len(services),
            "business_service_count": len(business_services),
        }

    def _network_context(self, finding):
        empty = {
            "subscriptions": [],
            "network_paths": [],
            "hub_dependencies": [],
            "firewall_impact": [],
            "nsg_impact": [],
            "notes": [],
        }
        service = self.network_lookup() if callable(self.network_lookup) else self.network_lookup
        if service is None:
            empty["notes"] = ["network_provider_unavailable"]
            return empty
        snapshot = getattr(getattr(service, "topology", None), "snapshot", None)
        if snapshot is None:
            empty["notes"] = ["network_snapshot_unavailable"]
            return empty
        resource_key = str(finding.get("_resource_key") or "")
        nic = next((item for item in snapshot.nics if str(item.attached_resource_id or "") == resource_key), None)
        if nic is None:
            empty["notes"] = [f"network_resource_not_observed:{resource_key[:128]}"]
            return empty
        subnet = next((item for item in snapshot.subnets if item.resource_id == nic.subnet_id), None)
        vnet_id = str(subnet.vnet_id if subnet else "")
        subscriptions = sorted({value for value in (nic.subscription_id, getattr(subnet, "subscription_id", "")) if value})[: self.max_items]
        path_summaries = self._path_summaries(service, nic, vnet_id)
        hub_dependencies = []
        if vnet_id and hasattr(service.topology, "hub_for"):
            hub_id = service.topology.hub_for(vnet_id)
            if hub_id:
                hub_dependencies.append(hub_id)
        rule_findings = [item.to_dict() for item in getattr(service, "rule_findings", ()) if self._relevant_rule(item, nic, subnet)]
        return {
            "subscriptions": subscriptions,
            "network_paths": path_summaries[: self.max_items],
            "hub_dependencies": hub_dependencies[: self.max_items],
            "firewall_impact": [row for row in rule_findings if row.get("control") == "firewall"][: self.max_items],
            "nsg_impact": [row for row in rule_findings if row.get("control") == "nsg"][: self.max_items],
            "notes": [],
        }

    def _path_summaries(self, service, nic, vnet_id):
        summaries = []
        topology = getattr(service, "topology", None)
        if topology is not None and vnet_id:
            role = topology.role_of(vnet_id)
            peers = list(topology.peers_of(vnet_id))[: self.max_items]
            if role != "unknown":
                text = f"{nic.name or nic.resource_id} is in a {role} VNet"
                if peers:
                    text += f" peered with {', '.join(peers[:3])}"
                summaries.append(text[:512])
        try:
            result = service.validate_flow(FlowQuery(source=nic.resource_id, destination="Internet", protocol="Tcp"))
        except (LookupError, ValueError):
            result = None
        if isinstance(result, FlowResult):
            path = result.path_summary or self._hop_summary(result.hops)
            if path:
                summaries.append(path[:512])
        return summaries

    @staticmethod
    def _hop_summary(hops: tuple[FlowHop, ...] | list[FlowHop]) -> str:
        labels = [hop.control for hop in hops if getattr(hop, "control", "")]
        return " -> ".join(labels)

    @staticmethod
    def _relevant_rule(item, nic, subnet):
        control_id = str(getattr(item, "control_id", "") or "")
        rule_id = str(getattr(item, "rule_id", "") or "")
        texts = {control_id.casefold(), rule_id.casefold()}
        if nic.nsg_id and nic.nsg_id.casefold() in texts:
            return True
        return bool(subnet and getattr(subnet, "nsg_id", "") and str(subnet.nsg_id).casefold() in texts)
