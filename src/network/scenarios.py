"""Deterministic, policy-opted-in design review over the existing scoped snapshot."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from api.evidence import classify_freshness
from operations.network_scenarios import NETWORK_DESIGN_REVIEW

from .design import PolicyRule
from .models import (
    FABRIC_CAPACITY_RESOURCE_TYPE,
    PRIVATE_LINK_RESOURCE_TYPES,
    NetworkResource,
    NetworkSecurityRule,
    PrivateEndpoint,
)
from .service import NetworkIntelligenceService
from .tightening import SEVERITY_ORDER, RuleTighteningAnalyzer

PRIVATE, PEERING, NSG = NETWORK_DESIGN_REVIEW["parameters"]
NSG_CATEGORIES = {
    "internet_inbound",
    "any_any",
    "wide_source_cidr",
    "broad_port_range",
    "sensitive_port_exposure",
}


def _strings(value: Any) -> list[str] | None:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(v, str) and v.strip() for v in value)
    ):
        return None
    return [v.strip().casefold() for v in value]


def _exception(rule: PolicyRule, resource_id: str, now: datetime) -> tuple[str, str]:
    for entry in rule.parameters.get("exceptions", []):
        if (
            not isinstance(entry, dict)
            or str(entry.get("resource_id", "")).casefold() != resource_id
        ):
            continue
        reference = str(entry.get("reference") or "").strip()
        try:
            expires = datetime.fromisoformat(str(entry.get("expires_at", "")))
        except ValueError:
            continue
        if reference and expires.tzinfo is not None:
            return reference, "active" if expires > now else "expired"
    return "", ""


def _known_nsg_rule(rule: NetworkSecurityRule) -> bool:
    return (
        rule.configuration_observed
        and rule.priority > 0
        and rule.direction.casefold() in {"inbound", "outbound"}
        and rule.access.casefold() in {"allow", "deny"}
        and rule.protocol.casefold() in {"*", "any", "tcp", "udp", "icmp", "esp", "ah"}
        and all(
            spec.is_any or bool(spec.ranges)
            for spec in (
                rule.source_port_spec,
                rule.destination_port_spec,
            )
        )
    )


def review_network_design(
    service: NetworkIntelligenceService,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate three bounded scenarios, never acquiring data or inferring reachability."""
    now = now or datetime.now(UTC)
    snapshot = service.snapshot
    policy_version = hashlib.sha256(
        json.dumps(service.policy.to_dict(), sort_keys=True, default=str).encode()
    ).hexdigest()
    assessments: list[dict[str, Any]] = []
    freshness = classify_freshness(snapshot.observed_at, now=now)
    endpoints_by_target: dict[str, list[PrivateEndpoint]] = {}
    for endpoint in snapshot.private_endpoints:
        endpoints_by_target.setdefault(endpoint.target_resource_id, []).append(endpoint)
    zones = {z.resource_id: z for z in snapshot.private_dns_zones}
    subnets = {s.resource_id: s for s in snapshot.subnets}

    def add(
        scenario: str,
        check: str,
        resource: NetworkResource | None,
        status: str,
        detail: str,
        *,
        title: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> None:
        rule = service.policy.rule(scenario)
        reference, exception_status = (
            _exception(rule, resource.resource_id, now)
            if rule and resource
            else ("", "")
        )
        original_status = status
        if exception_status == "active":
            status = "excepted"
        resource_id = resource.resource_id if resource else ""
        identity = hashlib.sha256(
            f"{scenario}|{check}|{resource_id}|{policy_version}".encode()
        ).hexdigest()[:24]
        assessments.append(
            {
                "gap_id": f"design-{identity}",
                "scenario_id": scenario,
                "policy_id": rule.rule_id if rule else "",
                "policy_version": policy_version,
                "check_id": check,
                "resource_id": resource_id,
                "resource_name": resource.name if resource else "",
                "category": check,
                "severity": rule.severity if rule else "info",
                "title": title or check.replace("_", " ").capitalize(),
                "status": status,
                "detail": detail,
                "freshness": freshness,
                "evidence_refs": ["snapshot:network", f"policy:{policy_version}"],
                "evidence": evidence or {},
                "exception_reference": reference,
                "exception_status": exception_status,
                "underlying_status": original_status,
                "recommendation": "Review this configuration and the cited policy; validate missing evidence before proposing a change.",
            }
        )

    for scenario in (PRIVATE, PEERING, NSG):
        rule = service.policy.rule(scenario)
        if rule is None or not rule.enabled:
            add(
                scenario,
                "policy_not_declared",
                None,
                "unknown",
                "No explicit enabled scenario policy was supplied.",
            )
            continue
        exceptions = rule.parameters.get("exceptions", [])
        invalid_exceptions = not isinstance(exceptions, list) or any(
            not isinstance(entry, dict)
            or not all(
                isinstance(entry.get(key), str) and entry[key].strip()
                for key in ("resource_id", "reference", "expires_at")
            )
            for entry in exceptions
        )
        if not invalid_exceptions:
            exception_ids = [entry["resource_id"].casefold() for entry in exceptions]
            invalid_exceptions = len(exception_ids) != len(set(exception_ids))
            for entry in exceptions:
                try:
                    invalid_exceptions |= (
                        datetime.fromisoformat(entry["expires_at"]).tzinfo is None
                    )
                except ValueError:
                    invalid_exceptions = True
        if invalid_exceptions:
            add(
                scenario,
                "invalid_policy",
                None,
                "unknown",
                "Scenario exceptions require unique resource_id entries, reference and timezone-qualified expires_at.",
            )
            continue
        if scenario == PRIVATE:
            types = _strings(rule.parameters.get("resource_types"))
            if not types:
                add(
                    scenario,
                    "invalid_policy",
                    None,
                    "unknown",
                    "An explicit nonempty resource_types list is required.",
                )
                continue
            resources = sorted(
                (
                    r
                    for r in snapshot.private_link_resources
                    if r.resource_type in types
                ),
                key=lambda r: r.resource_id,
            )
            if not resources:
                add(
                    scenario,
                    "resource_coverage_unknown",
                    None,
                    "unknown",
                    "No applicable service resources were observed; acquisition completeness is unqualified.",
                )
            for resource in resources:
                if (
                    resource.resource_type not in PRIVATE_LINK_RESOURCE_TYPES
                    or resource.resource_type == FABRIC_CAPACITY_RESOURCE_TYPE
                ):
                    add(
                        scenario,
                        "service_semantics_unknown",
                        resource,
                        "unknown",
                        "Resource-level public access does not establish this service's private-access semantics.",
                    )
                    continue
                setting = resource.public_network_access.casefold()
                if setting == "enabled":
                    add(
                        scenario,
                        "public_access_enabled",
                        resource,
                        "violation",
                        "Public network access is explicitly Enabled against the declared private-access policy; endpoint presence does not disable it.",
                        evidence={
                            "public_network_access": resource.public_network_access,
                            "resource_type": resource.resource_type,
                        },
                    )
                elif setting == "disabled":
                    add(
                        scenario,
                        "public_access_disabled",
                        resource,
                        "observed",
                        "Public network access is explicitly Disabled; this does not prove private connectivity.",
                        evidence={
                            "public_network_access": resource.public_network_access,
                            "resource_type": resource.resource_type,
                        },
                    )
                else:
                    add(
                        scenario,
                        "public_access_unknown",
                        resource,
                        "unknown",
                        "Public network access is absent or has unsupported service-specific semantics; no default is inferred.",
                    )
                endpoints = endpoints_by_target.get(resource.resource_id, [])
                if not endpoints:
                    add(
                        scenario,
                        "endpoint_coverage_unknown",
                        resource,
                        "unknown",
                        "No in-scope endpoint was observed; missing or out-of-scope evidence is not a proven violation.",
                    )
                elif not any(
                    e.connection_state.casefold() == "approved" for e in endpoints
                ):
                    states = {e.connection_state.casefold() for e in endpoints}
                    known_failure = states <= {"rejected", "disconnected", "pending"}
                    add(
                        scenario,
                        "endpoint_not_approved"
                        if known_failure
                        else "endpoint_approval_unknown",
                        resource,
                        "violation" if known_failure else "unknown",
                        "No observed endpoint is Approved; connection approval is required by this private-access policy.",
                        evidence={"observed_connection_states": sorted(states)},
                    )
                else:
                    add(
                        scenario,
                        "endpoint_approved",
                        resource,
                        "observed",
                        "At least one in-scope endpoint connection is Approved; approval alone does not prove private resolution or disable public access.",
                        evidence={
                            "approved_endpoint_count": sum(
                                e.connection_state.casefold() == "approved"
                                for e in endpoints
                            )
                        },
                    )
                bound = any(
                    zone in zones
                    and endpoint.subnet_id in subnets
                    and subnets[endpoint.subnet_id].vnet_id
                    in zones[zone].linked_vnet_ids
                    for endpoint in endpoints
                    for zone in endpoint.private_dns_zone_ids
                )
                add(
                    scenario,
                    "dns_binding_observed" if bound else "dns_binding_unknown",
                    resource,
                    "observed" if bound else "unknown",
                    "A zone binding and endpoint VNet link were observed; DNS resolution is not demonstrated."
                    if bound
                    else "Private DNS binding/VNet-link evidence is incomplete; resolution is not demonstrated.",
                )
        elif scenario == PEERING:
            if not isinstance(
                rule.parameters.get("require_gateway_transit", False), bool
            ):
                add(
                    scenario,
                    "invalid_policy",
                    None,
                    "unknown",
                    "require_gateway_transit must be a boolean.",
                )
                continue
            vnets = {v.resource_id: v for v in snapshot.vnets}
            by_pair = {
                (p.local_vnet_id, p.remote_vnet_id): p for p in snapshot.peerings
            }
            pair_counts = Counter(
                (p.local_vnet_id, p.remote_vnet_id) for p in snapshot.peerings
            )
            seen = set()
            if not snapshot.peerings:
                add(
                    scenario,
                    "peering_coverage_unknown",
                    None,
                    "unknown",
                    "No peerings observed; acquisition completeness is unqualified.",
                )
            for peer in sorted(snapshot.peerings, key=lambda p: p.resource_id):
                if peer.peering_state:
                    add(
                        scenario,
                        "peering_state",
                        peer,
                        "observed" if peer.is_connected else "violation",
                        f"Observed peering state: {peer.peering_state}.",
                        evidence={"peering_state": peer.peering_state},
                    )
                else:
                    add(
                        scenario,
                        "peering_state_unknown",
                        peer,
                        "unknown",
                        "Peering state was not observed.",
                    )
                local, remote = (
                    vnets.get(peer.local_vnet_id),
                    vnets.get(peer.remote_vnet_id),
                )
                reverse = by_pair.get((peer.remote_vnet_id, peer.local_vnet_id))
                if (
                    not local
                    or not remote
                    or not reverse
                    or pair_counts[(peer.local_vnet_id, peer.remote_vnet_id)] != 1
                    or pair_counts[(peer.remote_vnet_id, peer.local_vnet_id)] != 1
                ):
                    add(
                        scenario,
                        "peer_coverage_unknown",
                        peer,
                        "unknown",
                        "Both in-scope VNets and an unambiguous reverse peering were not observed; remote identity is withheld.",
                    )
                    continue
                pair = tuple(sorted((local.resource_id, remote.resource_id)))
                if pair not in seen:
                    seen.add(pair)
                    try:
                        left = [
                            ipaddress.ip_network(c, strict=False)
                            for c in local.address_spaces
                        ]
                        right = [
                            ipaddress.ip_network(c, strict=False)
                            for c in remote.address_spaces
                        ]
                    except ValueError:
                        left, right = [], []
                    if not left or not right:
                        add(
                            scenario,
                            "address_coverage_unknown",
                            peer,
                            "unknown",
                            "One or both VNet address spaces are missing or invalid.",
                        )
                    else:
                        overlaps = any(
                            a.version == b.version and a.overlaps(b)
                            for a in left
                            for b in right
                        )
                        add(
                            scenario,
                            "address_overlap" if overlaps else "address_disjoint",
                            peer,
                            "violation" if overlaps else "observed",
                            "Observed VNet address spaces overlap."
                            if overlaps
                            else "Observed VNet address spaces do not overlap.",
                            evidence={
                                "local_address_spaces": list(local.address_spaces),
                                "remote_address_spaces": list(remote.address_spaces),
                            },
                        )
                if (
                    not peer.gateway_flags_observed
                    or not reverse.gateway_flags_observed
                ):
                    add(
                        scenario,
                        "gateway_flags_unknown",
                        peer,
                        "unknown",
                        "Gateway flags were not explicitly observed on both sides; default false values are not evidence.",
                    )
                    continue
                invalid_transit = peer.use_remote_gateways and (
                    not reverse.allow_gateway_transit or peer.allow_gateway_transit
                )
                required = rule.parameters.get("require_gateway_transit", False)
                intended = not required or (
                    (
                        not service.policy.declares_hub(local.name)
                        or peer.allow_gateway_transit
                    )
                    and (
                        not service.policy.declares_hub(remote.name)
                        or peer.use_remote_gateways
                    )
                )
                if required and not service.policy.hub_vnet_names:
                    add(
                        scenario,
                        "gateway_intent_unknown",
                        peer,
                        "unknown",
                        "Gateway transit is required but no reviewed hub names were declared.",
                    )
                else:
                    add(
                        scenario,
                        "gateway_transit",
                        peer,
                        "violation" if invalid_transit or not intended else "observed",
                        "Gateway transit uses complementary allow_gateway_transit/use_remote_gateways flags; identical flags are not required.",
                        evidence={
                            "allow_gateway_transit": peer.allow_gateway_transit,
                            "use_remote_gateways": peer.use_remote_gateways,
                            "reverse_allow_gateway_transit": reverse.allow_gateway_transit,
                            "reverse_use_remote_gateways": reverse.use_remote_gateways,
                        },
                    )
        else:
            categories = _strings(rule.parameters.get("categories"))
            directions = _strings(rule.parameters.get("directions"))
            if (
                not categories
                or not set(categories) <= NSG_CATEGORIES
                or not directions
                or not set(directions) <= {"inbound", "outbound"}
            ):
                add(
                    scenario,
                    "invalid_policy",
                    None,
                    "unknown",
                    "Explicit supported categories and directions are required.",
                )
                continue
            for nsg in snapshot.nsgs:
                for nsg_rule in nsg.rules:
                    if not _known_nsg_rule(nsg_rule):
                        add(
                            scenario,
                            "nsg_rule_evidence_unknown",
                            nsg_rule,
                            "unknown",
                            "Rule fields were not explicitly observed; normalizer defaults cannot establish configured exposure.",
                        )
            reviewed_snapshot = replace(
                snapshot,
                nsgs=tuple(
                    replace(
                        nsg,
                        rules=tuple(r for r in nsg.rules if _known_nsg_rule(r)),
                    )
                    for nsg in snapshot.nsgs
                ),
            )
            analyzer = RuleTighteningAnalyzer(reviewed_snapshot)
            findings = analyzer.analyze()
            shadowed = {f.rule_id for f in findings if f.category == "shadowed"}
            rules = {r.resource_id: r for n in snapshot.nsgs for r in n.rules}
            if not rules:
                add(
                    scenario,
                    "nsg_coverage_unknown",
                    None,
                    "unknown",
                    "No NSG rules were observed; acquisition completeness is unqualified.",
                )
            for finding in findings:
                nsg_rule = rules.get(finding.rule_id)
                if (
                    finding.control != "nsg"
                    or finding.category not in categories
                    or not nsg_rule
                    or nsg_rule.direction.casefold() not in directions
                    or finding.rule_id in shadowed
                ):
                    continue
                add(
                    scenario,
                    finding.category,
                    nsg_rule,
                    "violation",
                    f"Observed {nsg_rule.direction} Allow rule at priority {nsg_rule.priority}: "
                    f"{nsg_rule.protocol} {nsg_rule.source_address}:{nsg_rule.source_port} "
                    f"to {nsg_rule.destination_address}:{nsg_rule.destination_port}. "
                    "Configured rule risk against reviewed policy, not demonstrated end-to-end reachability.",
                    title=f"Reviewed NSG configured risk: {finding.category.replace('_', ' ')}",
                    evidence={
                        **finding.evidence,
                        "priority": nsg_rule.priority,
                        "direction": nsg_rule.direction,
                        "source_port": nsg_rule.source_port,
                    },
                )
            if rules and not any(row["scenario_id"] == NSG for row in assessments):
                add(
                    scenario,
                    "no_matching_observed_rules",
                    None,
                    "observed",
                    "No unshadowed configured rule matched the reviewed risk categories and directions in the supplied snapshot; this is not an estate-wide compliance assertion.",
                )

    counts = Counter(row["status"] for row in assessments)
    gaps = sorted(
        (row for row in assessments if row["status"] == "violation"),
        key=lambda row: (
            SEVERITY_ORDER.get(row["severity"], 9),
            row["scenario_id"],
            row["resource_id"],
            row["check_id"],
        ),
    )
    summary = (
        f"Network design review v1: {len(gaps)} policy findings, {counts['unknown']} unknown checks, "
        f"{counts['excepted']} exceptions. Acquisition coverage is unknown; snapshot freshness: {freshness}. "
        "Configured risk only, not proven reachability or DNS resolution."
    )
    return {
        "gaps": gaps,
        "rule_findings": [],
        "design_review": {
            "version": "1",
            "policy_version": policy_version,
            "evaluated_window": {
                "observed_at": snapshot.observed_at,
                "evaluated_at": now.isoformat(),
            },
            "freshness": freshness,
            "coverage": {
                "acquisition_complete": None,
                "complete": False,
                "assessment_count": len(assessments),
                "finding_count": len(gaps),
                "resource_counts": snapshot.counts(),
            },
            "unknown_count": counts["unknown"],
            "exception_count": counts["excepted"],
            "summary": summary,
            "assessments": assessments,
            "evidence_sources": {
                "snapshot:network": {
                    "source": "scoped_network_snapshot",
                    "observed_at": snapshot.observed_at,
                },
                f"policy:{policy_version}": {
                    "source": "reviewed_network_policy",
                    "version": policy_version,
                    "rules": [
                        {
                            "policy_id": rule.rule_id,
                            "enabled": rule.enabled,
                            "parameters": {
                                k: v
                                for k, v in rule.parameters.items()
                                if k
                                in NETWORK_DESIGN_REVIEW["parameters"][rule.rule_id]
                                and k != "exceptions"
                            },
                        }
                        for rule in service.policy.rules
                        if rule.rule_id in (PRIVATE, PEERING, NSG)
                    ],
                },
            },
        },
    }
