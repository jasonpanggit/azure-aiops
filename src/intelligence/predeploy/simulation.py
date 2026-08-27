"""Deterministic simulation of proposed change effects, by domain.

Each simulator inspects the before/after property values of a resource change
and reports what the *declared configuration* would become. This is a
transformation of the plan, not a probe of a running system: no traffic is
sent, no control plane is called, no runtime behaviour is measured.

That boundary is the reason every simulated effect carries an explicit
``basis`` of ``declared_configuration``. A route change can be shown to remove
a next hop; whether a given flow actually breaks depends on effective routes,
peering, and NSG evaluation order that only Azure can resolve. Those are
emitted as ``requires_validation`` items rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import DESTRUCTIVE_ACTIONS, ProposedChange, ProposedResourceChange

DOMAIN_ROUTE = "route"
DOMAIN_FIREWALL = "firewall"
DOMAIN_NSG = "nsg"
DOMAIN_PRIVATE_ENDPOINT = "private_endpoint"
DOMAIN_IDENTITY = "identity"
DOMAIN_COMPUTE = "compute"
DOMAIN_DATA_SERVICE = "data_service"

SIMULATION_DOMAINS: tuple[str, ...] = (
    DOMAIN_ROUTE,
    DOMAIN_FIREWALL,
    DOMAIN_NSG,
    DOMAIN_PRIVATE_ENDPOINT,
    DOMAIN_IDENTITY,
    DOMAIN_COMPUTE,
    DOMAIN_DATA_SERVICE,
)

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_INFO = "info"

_SEVERITY_RANK = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1, SEVERITY_INFO: 0}

# Resource-type fragments that route a change to a simulator. Matched as
# substrings because type strings differ between Terraform
# (``azurerm_route_table``) and ARM (``Microsoft.Network/routeTables``).
_DOMAIN_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (DOMAIN_ROUTE, ("route_table", "routetables", "route")),
    (DOMAIN_FIREWALL, ("firewall", "azurefirewall")),
    (DOMAIN_NSG, ("network_security_group", "networksecuritygroups", "security_rule", "securityrules")),
    (DOMAIN_PRIVATE_ENDPOINT, ("private_endpoint", "privateendpoints", "private_dns", "privatednszones")),
    (DOMAIN_IDENTITY, ("role_assignment", "roleassignments", "role_definition", "user_assigned_identity", "userassignedidentities", "key_vault_access_policy")),
    (DOMAIN_COMPUTE, ("virtual_machine", "virtualmachines", "kubernetes_cluster", "managedclusters", "app_service", "linux_web_app", "windows_web_app", "sites", "container_app", "containerapps", "scale_set", "virtualmachinescalesets")),
    (DOMAIN_DATA_SERVICE, ("storage_account", "storageaccounts", "sql", "cosmosdb", "postgresql", "mysql", "redis", "databricks", "servers/databases")),
)


def classify_domain(change: ProposedResourceChange) -> str:
    """Best-effort domain for a resource change, or ``""`` when unrecognized."""
    haystack = f"{change.resource_type} {change.address}".casefold()
    for domain, fragments in _DOMAIN_MATCHERS:
        if any(fragment in haystack for fragment in fragments):
            return domain
    return ""


@dataclass(frozen=True)
class SimulatedEffect:
    """One predicted configuration outcome of a proposed change."""

    domain: str
    address: str
    effect: str
    severity: str = SEVERITY_INFO
    detail: str = ""
    requires_validation: tuple[str, ...] = ()
    # Every effect states what it was derived from. Only ever the declared
    # plan, never a live probe.
    basis: str = "declared_configuration"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "address": self.address,
            "effect": self.effect,
            "severity": self.severity,
            "detail": self.detail,
            "requires_validation": list(self.requires_validation),
            "basis": self.basis,
        }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _rule_identity(rule: Any) -> str:
    if isinstance(rule, Mapping):
        for key in ("name", "id", "rule_name"):
            if rule.get(key):
                return str(rule[key])
    return str(rule)


def _rule_delta(before: Any, after: Any) -> tuple[list[str], list[str]]:
    """Names present only before (removed) and only after (added)."""
    before_names = {_rule_identity(item) for item in _as_list(before)}
    after_names = {_rule_identity(item) for item in _as_list(after)}
    return sorted(before_names - after_names), sorted(after_names - before_names)


def _prop(change: ProposedResourceChange, *names: str) -> tuple[Any, Any]:
    for name in names:
        if name in change.before or name in change.after:
            return change.before.get(name), change.after.get(name)
    return None, None


def _destructive_effect(change: ProposedResourceChange, domain: str, noun: str) -> SimulatedEffect | None:
    if change.action not in DESTRUCTIVE_ACTIONS:
        return None
    verb = "deleted" if change.action == "delete" else "destroyed and recreated"
    return SimulatedEffect(
        domain=domain,
        address=change.address,
        effect=f"{noun}_{change.action}",
        severity=SEVERITY_HIGH,
        detail=f"The {noun.replace('_', ' ')} will be {verb}, interrupting its current behaviour.",
        requires_validation=(
            f"Confirm no active dependency relies on this {noun.replace('_', ' ')} during the change window.",
        ),
    )


def _simulate_route(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if destructive := _destructive_effect(change, DOMAIN_ROUTE, "route_table"):
        effects.append(destructive)
    before, after = _prop(change, "routes", "route")
    removed, added = _rule_delta(before, after)
    if removed:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_ROUTE,
                address=change.address,
                effect="routes_removed",
                severity=SEVERITY_HIGH,
                detail=f"Routes removed: {', '.join(removed)}. Traffic matching them falls back to system routes.",
                requires_validation=(
                    "Run Network Watcher next-hop for affected sources to confirm the effective route after removal.",
                ),
            )
        )
    if added:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_ROUTE,
                address=change.address,
                effect="routes_added",
                severity=SEVERITY_MEDIUM,
                detail=f"Routes added: {', '.join(added)}. More specific prefixes will override existing paths.",
                requires_validation=(
                    "Confirm the new next hop is reachable and does not create an asymmetric or black-holed path.",
                ),
            )
        )
    return effects


def _simulate_firewall(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if destructive := _destructive_effect(change, DOMAIN_FIREWALL, "firewall"):
        effects.append(destructive)
    before, after = _prop(change, "rules", "rule_collection", "network_rule_collection", "application_rule_collection")
    removed, added = _rule_delta(before, after)
    if removed:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_FIREWALL,
                address=change.address,
                effect="firewall_rules_removed",
                severity=SEVERITY_HIGH,
                detail=f"Firewall rules removed: {', '.join(removed)}. Flows they permitted will be denied.",
                requires_validation=("Confirm no production flow depends on the removed allow rules.",),
            )
        )
    if added:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_FIREWALL,
                address=change.address,
                effect="firewall_rules_added",
                severity=SEVERITY_MEDIUM,
                detail=f"Firewall rules added: {', '.join(added)}. New flows will be permitted.",
                requires_validation=("Review added allow rules against the network exposure policy.",),
            )
        )
    return effects


# NSG rules that open a port to the internet are the single highest-signal
# misconfiguration in a pre-deployment review, so they are matched explicitly.
_INTERNET_SOURCES = {"internet", "*", "0.0.0.0/0", "any"}


def _simulate_nsg(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if destructive := _destructive_effect(change, DOMAIN_NSG, "network_security_group"):
        effects.append(destructive)
    before, after = _prop(change, "security_rule", "security_rules", "rules")
    removed, added = _rule_delta(before, after)
    if removed:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_NSG,
                address=change.address,
                effect="nsg_rules_removed",
                severity=SEVERITY_HIGH,
                detail=f"NSG rules removed: {', '.join(removed)}. Traffic they allowed will be blocked by the default deny.",
                requires_validation=(
                    "Run an IP-flow verify for representative source/destination pairs before deployment.",
                ),
            )
        )
    for rule in _as_list(after):
        if not isinstance(rule, Mapping):
            continue
        access = str(rule.get("access") or "").casefold()
        direction = str(rule.get("direction") or "").casefold()
        source = str(rule.get("source_address_prefix") or rule.get("sourceAddressPrefix") or "").casefold()
        if access == "allow" and direction == "inbound" and source in _INTERNET_SOURCES:
            effects.append(
                SimulatedEffect(
                    domain=DOMAIN_NSG,
                    address=change.address,
                    effect="internet_inbound_exposure",
                    severity=SEVERITY_HIGH,
                    detail=(
                        f"Rule {_rule_identity(rule)} would allow inbound traffic from {source or 'any source'} "
                        f"to port(s) {rule.get('destination_port_range') or rule.get('destinationPortRange') or 'unspecified'}."
                    ),
                    requires_validation=(
                        "Confirm this exposure is intended and covered by a compensating control.",
                    ),
                )
            )
    if added and not any(effect.effect == "internet_inbound_exposure" for effect in effects):
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_NSG,
                address=change.address,
                effect="nsg_rules_added",
                severity=SEVERITY_MEDIUM,
                detail=f"NSG rules added: {', '.join(added)}.",
                requires_validation=("Confirm added rules match the intended access policy.",),
            )
        )
    return effects


def _simulate_private_endpoint(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if destructive := _destructive_effect(change, DOMAIN_PRIVATE_ENDPOINT, "private_endpoint"):
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_PRIVATE_ENDPOINT,
                address=change.address,
                effect=destructive.effect,
                severity=SEVERITY_HIGH,
                detail=(
                    "Removing the private endpoint withdraws private connectivity; clients resolving "
                    "the private DNS record will lose their path to the service."
                ),
                requires_validation=(
                    "Confirm no workload depends on private-link connectivity to this service.",
                    "Verify the private DNS zone record is removed or repointed consistently.",
                ),
            )
        )
    before, after = _prop(change, "public_network_access_enabled", "publicNetworkAccess", "public_network_access")

    def _enabled(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return str(value).casefold() in {"true", "enabled", "yes", "1"}

    was, now = _enabled(before), _enabled(after)
    if was is not None and now is not None and was != now:
        if now:
            effects.append(
                SimulatedEffect(
                    domain=DOMAIN_PRIVATE_ENDPOINT,
                    address=change.address,
                    effect="public_network_access_enabled",
                    severity=SEVERITY_HIGH,
                    detail="Public network access will be turned on, exposing the service beyond private connectivity.",
                    requires_validation=("Confirm public exposure is approved and firewall rules constrain it.",),
                )
            )
        else:
            effects.append(
                SimulatedEffect(
                    domain=DOMAIN_PRIVATE_ENDPOINT,
                    address=change.address,
                    effect="public_network_access_disabled",
                    severity=SEVERITY_MEDIUM,
                    detail=(
                        "Public network access will be turned off. Clients not reaching the service over "
                        "private link will lose connectivity."
                    ),
                    requires_validation=(
                        "Confirm every client has a private path before disabling public access.",
                    ),
                )
            )
    return effects


def _simulate_identity(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if change.action in DESTRUCTIVE_ACTIONS:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_IDENTITY,
                address=change.address,
                effect="identity_grant_removed",
                severity=SEVERITY_HIGH,
                detail=(
                    "An identity assignment will be removed. Any workload authenticating through it "
                    "loses that permission at apply time."
                ),
                requires_validation=(
                    "Confirm no running workload depends on this assignment.",
                    "Verify a replacement grant exists if access must continue.",
                ),
            )
        )
    role_before, role_after = _prop(change, "role_definition_name", "roleDefinitionName", "role_definition_id")
    if role_after and role_before != role_after:
        privileged = str(role_after).casefold() in {"owner", "contributor", "user access administrator"}
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_IDENTITY,
                address=change.address,
                effect="role_assignment_changed",
                severity=SEVERITY_HIGH if privileged else SEVERITY_MEDIUM,
                detail=f"Role changes from {role_before or 'none'} to {role_after}.",
                requires_validation=(
                    "Confirm the assignment follows least privilege for its scope.",
                ),
            )
        )
    return effects


def _simulate_compute(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if change.action in DESTRUCTIVE_ACTIONS:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_COMPUTE,
                address=change.address,
                effect="compute_replaced_or_deleted",
                severity=SEVERITY_HIGH,
                detail=(
                    "The compute resource will be destroyed or recreated, which interrupts the workload "
                    "it hosts and discards any non-persisted local state."
                ),
                requires_validation=(
                    "Confirm a maintenance window or that capacity is drained before apply.",
                ),
            )
        )
    sku_before, sku_after = _prop(change, "sku", "sku_name", "vm_size", "size")
    if sku_after and sku_before != sku_after:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_COMPUTE,
                address=change.address,
                effect="compute_sku_changed",
                severity=SEVERITY_MEDIUM,
                detail=f"SKU changes from {sku_before or 'unset'} to {sku_after}, altering capacity and cost.",
                requires_validation=(
                    "Confirm the target SKU is available in the region and meets capacity requirements.",
                ),
            )
        )
    count_before, count_after = _prop(change, "instance_count", "node_count", "capacity")
    if count_after is not None and count_before is not None and count_after != count_before:
        try:
            scaling_down = int(count_after) < int(count_before)
        except (TypeError, ValueError):
            scaling_down = False
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_COMPUTE,
                address=change.address,
                effect="compute_scale_changed",
                severity=SEVERITY_MEDIUM if scaling_down else SEVERITY_LOW,
                detail=f"Instance count changes from {count_before} to {count_after}.",
                requires_validation=(
                    "Confirm remaining capacity satisfies peak load."
                    if scaling_down
                    else "Confirm quota supports the increased instance count.",
                ),
            )
        )
    return effects


def _simulate_data_service(change: ProposedResourceChange) -> list[SimulatedEffect]:
    effects: list[SimulatedEffect] = []
    if change.action in DESTRUCTIVE_ACTIONS:
        effects.append(
            SimulatedEffect(
                domain=DOMAIN_DATA_SERVICE,
                address=change.address,
                effect="data_service_replaced_or_deleted",
                severity=SEVERITY_HIGH,
                detail=(
                    "The data service will be destroyed or recreated. Data loss is possible unless a "
                    "verified backup and restore path exists."
                ),
                requires_validation=(
                    "Confirm a recent restorable backup exists and the restore has been rehearsed.",
                ),
            )
        )
    for name, label in (
        ("allow_blob_public_access", "blob public access"),
        ("min_tls_version", "minimum TLS version"),
        ("https_traffic_only_enabled", "HTTPS-only enforcement"),
        ("infrastructure_encryption_enabled", "infrastructure encryption"),
    ):
        before, after = _prop(change, name)
        if after is not None and before is not None and before != after:
            effects.append(
                SimulatedEffect(
                    domain=DOMAIN_DATA_SERVICE,
                    address=change.address,
                    effect="data_protection_setting_changed",
                    severity=SEVERITY_HIGH,
                    detail=f"{label} changes from {before} to {after}.",
                    requires_validation=(f"Confirm the new {label} satisfies the data protection standard.",),
                )
            )
    retention_before, retention_after = _prop(change, "retention_days", "backup_retention_days")
    if retention_after is not None and retention_before is not None:
        try:
            reduced = int(retention_after) < int(retention_before)
        except (TypeError, ValueError):
            reduced = False
        if reduced:
            effects.append(
                SimulatedEffect(
                    domain=DOMAIN_DATA_SERVICE,
                    address=change.address,
                    effect="retention_reduced",
                    severity=SEVERITY_HIGH,
                    detail=f"Retention drops from {retention_before} to {retention_after} days.",
                    requires_validation=("Confirm the reduced retention still meets the compliance obligation.",),
                )
            )
    return effects


_SIMULATORS = {
    DOMAIN_ROUTE: _simulate_route,
    DOMAIN_FIREWALL: _simulate_firewall,
    DOMAIN_NSG: _simulate_nsg,
    DOMAIN_PRIVATE_ENDPOINT: _simulate_private_endpoint,
    DOMAIN_IDENTITY: _simulate_identity,
    DOMAIN_COMPUTE: _simulate_compute,
    DOMAIN_DATA_SERVICE: _simulate_data_service,
}


@dataclass
class SimulationResult:
    effects: list[SimulatedEffect] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        by_domain: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for effect in self.effects:
            by_domain[effect.domain] = by_domain.get(effect.domain, 0) + 1
            by_severity[effect.severity] = by_severity.get(effect.severity, 0) + 1
        unknowns: list[str] = []
        if self.unclassified:
            unknowns.append(
                f"{len(self.unclassified)} proposed change(s) did not match a supported simulation "
                "domain, so their effect was not simulated."
            )
        return {
            "effects": [effect.to_dict() for effect in self.effects],
            "by_domain": by_domain,
            "by_severity": by_severity,
            "highest_severity": max(
                (effect.severity for effect in self.effects),
                key=lambda value: _SEVERITY_RANK.get(value, 0),
                default=SEVERITY_INFO,
            ),
            "unclassified_addresses": list(self.unclassified),
            "unknowns": unknowns,
            "simulated_domains": list(SIMULATION_DOMAINS),
            "basis": "declared_configuration",
            # Load-bearing disclaimer: these are configuration outcomes derived
            # from the plan, not observed runtime behaviour.
            "interpretation": (
                "Effects describe the configuration state the change would produce, derived from the "
                "submitted plan. No live traffic, control-plane call, or runtime probe was performed, "
                "so actual behaviour must be confirmed by the listed validations."
            ),
            "confirmed_outcome": False,
        }


def simulate(change: ProposedChange) -> dict[str, Any]:
    """Simulate every effective resource change in a proposed change set."""
    result = SimulationResult()
    for item in change.effective_changes:
        domain = classify_domain(item)
        simulator = _SIMULATORS.get(domain)
        if simulator is None:
            result.unclassified.append(item.address)
            continue
        result.effects.extend(simulator(item))
    return result.to_dict()
