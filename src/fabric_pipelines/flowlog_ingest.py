"""NSG-rule + flow-log directional topology join (D-11).

**Status:** supports both fixture and live-data joins. When a subscription
has Virtual Network flow logs + Traffic Analytics provisioned,
:func:`live_flow_logs_from_rows` maps ``NTANetAnalytics`` rows (queried via
``onboarding.monitor_logs.AzureMonitorLogsClient.query_nsg_flow_logs``) onto
the same :class:`FlowLogRecord` shape the fixture join already used, so
:func:`join_flow_logs_with_nsg_rules` requires no changes to consume live
data -- only the *source* of ``flow_logs`` changes. Call sites without live
Traffic Analytics wired up can keep using :func:`curated_flow_log_fixture`;
the 08-03 comparison report must flag any "allowed vs. observed" result
derived through the fixture path as fixture-only, not a live-traffic-
validated claim.

Flow log source: *Virtual network* flow logs, not NSG flow logs. NSG flow
logs were blocked for new creation in June 2025 and retire entirely in
September 2027; their Traffic Analytics table (``AzureNetworkAnalytics_CL``,
``_s``/``_d`` suffixed columns) is a different schema from the VNet table
(``NTANetAnalytics``, unsuffixed columns) and is not supported here.

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

from network.addressing import AddressSpec

#: Distinguishes fixture-derived edges from both AIOps's own source tag and
#: this pipeline's identity-derived edges (`topology_pipeline.SOURCE_TAG`),
#: so provenance never implies live-traffic validation it cannot back up.
FIXTURE_SOURCE_TAG = "fabric_pipeline:flowlog_fixture"

#: Tags edges derived from a real Traffic Analytics query, distinguishing
#: them from both the fixture tag above and identity-derived edges.
LIVE_SOURCE_TAG = "fabric_pipeline:flowlog_live"

_SCHEMA_VERSION = "1.0.0"

#: ``NTANetAnalytics.L4Protocol`` codes -> ARM NSG rule ``protocol`` values.
#: Traffic Analytics emits single letters; NSG rules use full names. Only
#: TCP and UDP are represented in flow logs, so anything else is dropped
#: rather than mapped to a plausible-looking guess.
_PROTOCOL_CODES = {"t": "Tcp", "u": "Udp", "tcp": "Tcp", "udp": "Udp"}

#: ``NTANetAnalytics.FlowStatus`` codes -> NSG rule ``access`` vocabulary.
_FLOW_STATUS_CODES = {"a": "Allow", "d": "Deny", "allow": "Allow", "deny": "Deny"}


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
    #: ``NTANetAnalytics.AclRule`` -- the NSG rule Azure reports as having
    #: actually decided this flow. Authoritative when present: it is what
    #: *did* happen, whereas CIDR matching only infers what *would* match.
    #: Blank for fixture rows and for flows no NSG evaluated.
    acl_rule: str = ""
    #: ``NTANetAnalytics.AclGroup`` -- the NSG containing :attr:`acl_rule`.
    acl_group: str = ""


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


def live_flow_logs_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[FlowLogRecord]:
    """Maps raw ``NTANetAnalytics`` rows (from
    ``AzureMonitorLogsClient.query_nsg_flow_logs``) onto :class:`FlowLogRecord`.

    Two vocabulary mismatches between Traffic Analytics and ARM's NSG rule
    representation are normalized here, so that neither :func:`_classify`
    nor :func:`_match_rule` needs a live-vs-fixture branch:

    * ``FlowStatus`` is ``"A"``/``"D"``; NSG rule ``access`` is
      ``"Allow"``/``"Deny"``.
    * ``L4Protocol`` is ``"T"``/``"U"``; NSG rule ``protocol`` is
      ``"Tcp"``/``"Udp"``/``"*"``.

    Rows missing a required field, or carrying a protocol/status code this
    mapping does not recognise, are dropped rather than guessed at -- an
    incomplete or unrecognised observation is not evidence (D-05).
    """
    records: list[FlowLogRecord] = []
    for row in rows:
        source = str(row.get("SrcIp") or "").strip()
        destination = str(row.get("DestIp") or "").strip()
        protocol_code = str(row.get("L4Protocol") or "").strip().casefold()
        port = row.get("DestPort")
        status = str(row.get("FlowStatus") or "").strip().casefold()
        observed_at = str(row.get("TimeGenerated") or "").strip()
        if not (source and destination and observed_at):
            continue
        protocol = _PROTOCOL_CODES.get(protocol_code)
        decision = _FLOW_STATUS_CODES.get(status)
        if protocol is None or decision is None:
            continue
        try:
            port_str = str(int(port))
        except (TypeError, ValueError):
            continue
        records.append(
            FlowLogRecord(
                source_address=source,
                destination_address=destination,
                destination_port=port_str,
                protocol=protocol,
                decision=decision,
                observed_at=observed_at,
                acl_rule=str(row.get("AclRule") or "").strip(),
                acl_group=str(row.get("AclGroup") or "").strip(),
            )
        )
    return records


def join_flow_logs_with_nsg_rules(
    rules: Sequence[Mapping[str, Any]],
    flow_logs: Sequence[FlowLogRecord],
    *,
    observed: str,
    live: bool = False,
) -> list[dict[str, Any]]:
    """Joins flow-log records against NSG rule rows on
    source/dest/port/protocol, producing directional ``topology_edges`` rows.

    A flow log matches a rule when its protocol and destination port fall
    within the rule's declared ranges and its source/destination addresses
    are CIDR-contained by the rule's declared ranges (via
    ``network.addressing.AddressSpec``, the same containment logic the rule
    tightening analyzer uses) -- not merely exact string equality.

    Set ``live=True`` when ``flow_logs`` came from a real Traffic Analytics
    query rather than :func:`curated_flow_log_fixture`; this raises edge
    confidence, tags provenance as ``accepted``/``traffic_analytics``, and
    switches the source tag from :data:`FIXTURE_SOURCE_TAG` to
    :data:`LIVE_SOURCE_TAG` so fixture and live-derived edges never collide
    on the same content-addressed ID and never get confused in the
    comparison report.
    """
    source_tag = LIVE_SOURCE_TAG if live else FIXTURE_SOURCE_TAG
    # Live observed traffic is direct ground truth, at parity with
    # identity-derived edges; fixture data stays capped below that range so
    # provenance never implies validation it cannot back up.
    confidence = 0.95 if live else 0.6
    data_source = "traffic_analytics" if live else "fixture"
    assertion_state = "accepted" if live else "fixture_only"

    edges: list[dict[str, Any]] = []
    for flow in flow_logs:
        match = _match_rule(rules, flow)
        if match is None:
            continue
        matched_rule, attribution = match
        predicate = "trafficObserved"
        subject = _flow_endpoint_id(flow.source_address, flow.destination_address, flow.protocol, flow.destination_port)
        obj = matched_rule["id"]
        edge = _add_edge(
            subject, predicate, obj, source_tag, observed, confidence, assertion_state=assertion_state
        )
        edge["attributes"] = {
            "ruleAccess": matched_rule.get("access"),
            "observedDecision": flow.decision,
            "isDefaultRule": matched_rule.get("isDefault", False),
            "allowedVsObserved": _classify(matched_rule.get("access"), flow.decision),
            "dataSource": data_source,
            # How the rule was identified. "acl_rule" means Azure told us
            # which rule fired; "cidr_match" means we inferred it. A consumer
            # should weight these differently.
            "attribution": attribution,
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
) -> tuple[Mapping[str, Any], str] | None:
    """Resolves the NSG rule that decided ``flow``, with its attribution method.

    Prefers ``AclRule`` -- Azure reporting which rule *actually* fired is
    ground truth, and beats re-deriving the decision ourselves. CIDR matching
    is the fallback for fixture rows and for flows Traffic Analytics did not
    attribute (returns the *first* matching rule, which approximates but does
    not replicate Azure's priority ordering).

    The returned tag records which method was used, so a consumer can tell an
    authoritative attribution from an inferred one instead of treating both
    as equally certain (D-05).
    """
    if flow.acl_rule:
        direct = _match_by_acl_rule(rules, flow)
        if direct is not None:
            return direct, "acl_rule"
        # Azure named a rule we do not hold (e.g. the NSG is outside the
        # ingested scope). Falling back to CIDR here would attribute the flow
        # to the wrong rule, so treat it as unattributable.
        return None

    for rule in rules:
        if rule.get("protocol") not in {"*", flow.protocol}:
            continue
        if not _address_matches(rule.get("destinationAddress", ""), flow.destination_address):
            continue
        if not _address_matches(rule.get("sourceAddress", ""), flow.source_address):
            continue
        if not _port_matches(rule.get("destinationPort", ""), flow.destination_port):
            continue
        return rule, "cidr_match"
    return None


def _match_by_acl_rule(
    rules: Sequence[Mapping[str, Any]], flow: FlowLogRecord
) -> Mapping[str, Any] | None:
    """Finds the rule Traffic Analytics named, scoped by NSG when known.

    ``AclRule`` is a rule *name*, not an id, and names are only unique within
    one NSG -- so ``AclGroup`` disambiguates when several NSGs use the same
    rule name. Without a group, an ambiguous name matches nothing rather than
    picking arbitrarily.
    """
    target = flow.acl_rule.casefold()
    group = flow.acl_group.casefold()
    candidates = [
        rule
        for rule in rules
        if str(rule.get("name") or "").strip().casefold() == target
    ]
    if group:
        scoped = [
            rule
            for rule in candidates
            if group in str(rule.get("nsgId") or rule.get("nsgName") or "").casefold()
        ]
        if scoped:
            candidates = scoped
    return candidates[0] if len(candidates) == 1 else None


def _address_matches(rule_address: str, flow_address: str) -> bool:
    """CIDR-aware containment check via ``AddressSpec`` (the same logic the
    rule tightening analyzer uses), not exact string equality. An
    unresolvable service tag returns ``False`` here -- unlike
    ``AddressSpec.contains_address``'s ``None`` (unknown), a flow-log join
    has no use for "maybe": either the rule demonstrably covers the
    observed address or it does not match."""
    spec = AddressSpec.parse(rule_address)
    return spec.contains_address(flow_address) is True


def _port_matches(rule_port: str, flow_port: str) -> bool:
    ports = {value.strip() for value in rule_port.split(",") if value.strip()}
    if "*" in ports:
        return True
    for port_range in ports:
        if "-" in port_range:
            low, _, high = port_range.partition("-")
            try:
                if int(low) <= int(flow_port) <= int(high):
                    return True
            except ValueError:
                continue
        elif port_range == flow_port:
            return True
    return False


def _flow_endpoint_id(source: str, destination: str, protocol: str, port: str) -> str:
    """Content-addressed synthetic identity for a flow-log observation --
    flow logs have no ARM resource ID, so the subject must be derived from
    the observation itself rather than fabricated as a fake resource_id."""
    digest = hashlib.sha256(f"{source}|{destination}|{protocol}|{port}".encode()).hexdigest()[:16]
    return f"flowlog-observation:{digest}"


def _add_edge(
    subject: str,
    predicate: str,
    obj: str,
    source: str,
    observed: str,
    confidence: float,
    *,
    assertion_state: str = "fixture_only",
) -> dict[str, Any]:
    """Same content-addressed ID scheme as ``topology_pipeline._add_edge`` /
    AIOps's ``normalize._add_edge`` -- one relationship-ID derivation rule
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
        "assertionState": assertion_state,
        "schemaVersion": _SCHEMA_VERSION,
    }


__all__ = [
    "FIXTURE_SOURCE_TAG",
    "LIVE_SOURCE_TAG",
    "FlowLogRecord",
    "curated_flow_log_fixture",
    "join_flow_logs_with_nsg_rules",
    "live_flow_logs_from_rows",
]
