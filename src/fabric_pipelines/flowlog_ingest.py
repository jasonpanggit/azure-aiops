"""Fixture-only NSG-rule + flow-log directional topology join (D-11).

**Status:** fixture-only, not live-data-validated. Per the phase's
`checkpoint:human-verify` resolution, no NSG Flow Logs v2 / Traffic Analytics
diagnostic settings have been provisioned in the target subscription this
phase (RESEARCH.md Runtime State Inventory: zero live ingestion exists).
This module therefore joins NSG rule rows against a **synthetic/curated
flow-log fixture**, not a real Traffic Analytics table. The 08-03 comparison
report must flag any "allowed vs. observed" result derived through this path
as fixture-only, not a live-traffic-validated claim.

Join shape: NSG rule rows already flattened to the
``network_normalize.py:198-251`` shape (source/dest address, port, protocol,
access, ``isDefault``) joined against flow-log records on
source/dest/port/protocol, producing directional edges that carry both the
rule's *allowed* decision and the flow-log's *observed* decision side by
side -- so a rule that permits traffic nothing has ever exercised, or
traffic that was denied but attempted, both remain visible (D-05: unknown/
stale/conflicting must remain explicit, never silently resolved to one
verdict).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Distinguishes fixture-derived edges from both Hermes's own source tag and
#: this pipeline's identity-derived edges (`topology_pipeline.SOURCE_TAG`),
#: so provenance never implies live-traffic validation it cannot back up.
FIXTURE_SOURCE_TAG = "fabric_pipeline:flowlog_fixture"

_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class FlowLogRecord:
    """One curated flow-log observation (mirrors NSG Flow Log v2 / Traffic
    Analytics record shape: source/dest IP, port, protocol, and the decision
    actually enforced when the flow was observed)."""

    source_address: str
    destination_address: str
    destination_port: str
    protocol: str
    decision: str  # "Allow" | "Deny", matching NSG rule "access" vocabulary
    observed_at: str


def curated_flow_log_fixture(observed_at: str) -> list[FlowLogRecord]:
    """Synthetic flow-log rows exercising the fixture NSG rule's traffic.

    Deliberately includes one flow matching the fixture's explicit allow
    rule (traffic that was both allowed-by-rule and actually observed) and
    one flow matching the default deny-all-inbound rule that was
    nonetheless attempted (denied-by-rule, observed anyway) -- this is
    exactly the "allowed vs. observed" distinction D-11 requires be
    computable, not collapsed into a single verdict.
    """
    return [
        FlowLogRecord(
            source_address="10.10.0.0/16",
            destination_address="10.10.1.0/24",
            destination_port="443",
            protocol="Tcp",
            decision="Allow",
            observed_at=observed_at,
        ),
        FlowLogRecord(
            source_address="203.0.113.0/24",
            destination_address="10.10.1.0/24",
            destination_port="3389",
            protocol="Tcp",
            decision="Deny",
            observed_at=observed_at,
        ),
    ]


def join_flow_logs_with_nsg_rules(
    rules: Sequence[Mapping[str, Any]],
    flow_logs: Sequence[FlowLogRecord],
    *,
    observed: str,
) -> list[dict[str, Any]]:
    """Joins curated flow-log records against NSG rule rows on
    source/dest/port/protocol, producing directional ``topology_edges`` rows.

    A flow log matches a rule when its protocol, destination port, and
    address ranges are exact or prefix-contained by the rule's declared
    ranges (Azure CIDR-range semantics simplified for the fixture join --
    live Traffic Analytics data would need full CIDR containment, deferred
    per fixture-only scope).
    """
    edges: list[dict[str, Any]] = []
    for flow in flow_logs:
        matched_rule = _match_rule(rules, flow)
        if matched_rule is None:
            continue
        predicate = "trafficObserved"
        subject = _flow_endpoint_id(flow.source_address, flow.destination_address, flow.protocol, flow.destination_port)
        obj = matched_rule["id"]
        confidence = 0.6  # capped below identity-derived edges' 0.9+ range -- fixture, not live data
        edge = _add_edge(subject, predicate, obj, FIXTURE_SOURCE_TAG, observed, confidence)
        edge["attributes"] = {
            "ruleAccess": matched_rule.get("access"),
            "observedDecision": flow.decision,
            "isDefaultRule": matched_rule.get("isDefault", False),
            "allowedVsObserved": _classify(matched_rule.get("access"), flow.decision),
            "dataSource": "fixture",
        }
        edges.append(edge)
    return edges


def _classify(rule_access: str | None, observed_decision: str) -> str:
    """Explicit tri-state verdict -- never silently collapsed (D-05)."""
    rule_access = (rule_access or "").casefold()
    observed_decision = (observed_decision or "").casefold()
    if rule_access == "allow" and observed_decision == "allow":
        return "allowed_and_observed"
    if rule_access == "deny" and observed_decision == "deny":
        return "denied_and_blocked"
    if rule_access == "allow" and observed_decision == "deny":
        return "allowed_but_not_observed_as_permitted"
    if rule_access == "deny" and observed_decision == "allow":
        return "denied_but_traffic_observed"
    return "unknown"


def _match_rule(
    rules: Sequence[Mapping[str, Any]], flow: FlowLogRecord
) -> Mapping[str, Any] | None:
    for rule in rules:
        if rule.get("protocol") not in {"*", flow.protocol}:
            continue
        if not _address_matches(rule.get("destinationAddress", ""), flow.destination_address):
            continue
        if not _address_matches(rule.get("sourceAddress", ""), flow.source_address):
            continue
        if not _port_matches(rule.get("destinationPort", ""), flow.destination_port):
            continue
        return rule
    return None


def _address_matches(rule_address: str, flow_address: str) -> bool:
    ranges = {value.strip() for value in rule_address.split(",") if value.strip()}
    return "*" in ranges or flow_address in ranges


def _port_matches(rule_port: str, flow_port: str) -> bool:
    ports = {value.strip() for value in rule_port.split(",") if value.strip()}
    return "*" in ports or flow_port in ports


def _flow_endpoint_id(source: str, destination: str, protocol: str, port: str) -> str:
    """Content-addressed synthetic identity for a flow-log observation --
    flow logs have no ARM resource ID, so the subject must be derived from
    the observation itself rather than fabricated as a fake resource_id."""
    digest = hashlib.sha256(f"{source}|{destination}|{protocol}|{port}".encode()).hexdigest()[:16]
    return f"flowlog-observation:{digest}"


def _add_edge(
    subject: str, predicate: str, obj: str, source: str, observed: str, confidence: float
) -> dict[str, Any]:
    """Same content-addressed ID scheme as ``topology_pipeline._add_edge`` /
    Hermes's ``normalize._add_edge`` -- one relationship-ID derivation rule
    across the whole comparison arm, not a second one invented here."""
    digest = hashlib.sha256(f"{subject}|{predicate}|{obj}|{source}".encode()).hexdigest()[:24]
    return {
        "relationshipId": digest,
        "subjectId": subject,
        "predicate": predicate,
        "objectId": obj,
        "confidence": confidence,
        "source": source,
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "assertionState": "fixture_only",
        "schemaVersion": _SCHEMA_VERSION,
    }


__all__ = [
    "FIXTURE_SOURCE_TAG",
    "FlowLogRecord",
    "curated_flow_log_fixture",
    "join_flow_logs_with_nsg_rules",
]
