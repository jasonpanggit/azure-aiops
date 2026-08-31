"""Firewall and NSG rule tightening analysis.

Finds rules that are broader than they need to be, rules that can never fire,
and rules nobody owns. Each finding names the rule, explains why it was
flagged, and states what evidence supports it — a finding you cannot defend
in a change review is noise.

Deliberate limitation: "unused" is inferred **structurally** (a rule that is
shadowed, or one whose target subnet has no attached workload) -- never from
observed traffic. Findings say so. Flow-log ingestion now exists
(``fabric_pipelines.flowlog_ingest``) and produces ``trafficObserved`` edges,
but this analyzer does not yet consume them, so a rule flagged here as
unused is "structurally unreachable", not "never exercised in practice".
Wiring those edges in would let this module distinguish the two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .addressing import SENSITIVE_PORTS, AddressSpec
from .models import (
    FirewallRule,
    FirewallRuleCollection,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

#: A source prefix at or below this length is "wide" (/16 and broader).
WIDE_PREFIX_THRESHOLD = 16

#: Ports beyond this count in one rule counts as an overly broad port range.
BROAD_PORT_THRESHOLD = 100

#: Tag keys consulted when attributing ownership.
OWNER_TAG_KEYS = ("owner", "ownedby", "owner_email", "contact", "team", "supportteam")

#: Environment names treated as production for cross-environment analysis.
PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production", "prd"})
NON_PRODUCTION_ENVIRONMENTS = frozenset(
    {"dev", "development", "test", "tst", "uat", "qa", "stage", "staging", "sandbox"}
)


@dataclass(frozen=True)
class RuleFinding:
    """One tightening finding against one rule."""

    finding_id: str
    category: str
    severity: str
    rule_id: str
    rule_name: str
    control: str
    control_id: str
    title: str
    detail: str
    evidence: dict[str, Any]
    recommendation: str
    connection_id: str = ""
    subscription_id: str = ""
    environment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "category": self.category,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "control": self.control,
            "control_id": self.control_id,
            "title": self.title,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "recommendation": self.recommendation,
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "environment": self.environment,
        }


def _finding_id(category: str, rule_id: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{category}|{rule_id}".encode()).hexdigest()[:16]
    return f"netrule-{digest}"


def _environment_class(value: str) -> str:
    token = str(value or "").strip().casefold()
    if token in PRODUCTION_ENVIRONMENTS:
        return "production"
    if token in NON_PRODUCTION_ENVIRONMENTS:
        return "non-production"
    return "unknown"


def _has_owner(tags: dict[str, str], *extra: str) -> bool:
    if any(str(value or "").strip() for value in extra):
        return True
    folded = {str(key).casefold(): str(value) for key, value in tags.items()}
    return any(folded.get(key, "").strip() for key in OWNER_TAG_KEYS)


class RuleTighteningAnalyzer:
    """Analyzes NSG and firewall rules for over-permissiveness and dead rules."""

    def __init__(self, snapshot: NetworkSnapshot) -> None:
        self.snapshot = snapshot
        self._subnets = {subnet.resource_id: subnet for subnet in snapshot.subnets}
        self._nics_by_subnet: dict[str, int] = {}
        for nic in snapshot.nics:
            if nic.subnet_id:
                self._nics_by_subnet[nic.subnet_id] = self._nics_by_subnet.get(nic.subnet_id, 0) + 1

    def analyze(self) -> tuple[RuleFinding, ...]:
        findings: list[RuleFinding] = []
        for nsg in self.snapshot.nsgs:
            findings.extend(self._analyze_nsg(nsg))
        for collection in self.snapshot.firewall_collections:
            findings.extend(self._analyze_firewall_collection(collection))
        return tuple(
            sorted(
                findings,
                key=lambda item: (SEVERITY_ORDER.get(item.severity, 9), item.category, item.rule_id),
            )
        )

    def _analyze_nsg(self, nsg: NetworkSecurityGroup) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        custom_rules = [rule for rule in nsg.rules if not rule.is_default]

        for rule in custom_rules:
            findings.extend(self._analyze_nsg_rule(nsg, rule))

        findings.extend(self._detect_shadowed(nsg, custom_rules))
        findings.extend(self._detect_unattached(nsg))
        return findings

    def _analyze_nsg_rule(
        self, nsg: NetworkSecurityGroup, rule: NetworkSecurityRule
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        if not rule.is_allow:
            return findings

        source = rule.source_spec
        destination = rule.destination_spec
        ports = rule.destination_port_spec
        protocol = rule.protocol_spec
        environment = rule.environment or nsg.environment

        def add(
            category: str,
            severity: str,
            title: str,
            detail: str,
            evidence: dict[str, Any],
            recommendation: str,
        ) -> None:
            findings.append(
                RuleFinding(
                    finding_id=_finding_id(category, rule.resource_id),
                    category=category,
                    severity=severity,
                    rule_id=rule.resource_id,
                    rule_name=rule.name,
                    control="nsg",
                    control_id=nsg.resource_id,
                    title=title,
                    detail=detail,
                    evidence=evidence,
                    recommendation=recommendation,
                    connection_id=rule.connection_id or nsg.connection_id,
                    subscription_id=rule.subscription_id or nsg.subscription_id,
                    environment=environment,
                )
            )

        if source.is_any and destination.is_any and ports.is_any and protocol.is_any:
            add(
                "any_any",
                "critical",
                "Rule allows any source to any destination on any port",
                (
                    f"'{rule.name}' (priority {rule.priority}, {rule.direction}) permits all "
                    "traffic. This rule provides no security value and masks every rule below it."
                ),
                {
                    "source": rule.source_address,
                    "destination": rule.destination_address,
                    "port": rule.destination_port,
                    "protocol": rule.protocol,
                },
                "Replace with explicit source, destination, protocol, and port values.",
            )

        if rule.is_inbound and source.is_internet:
            exposed = ports.sensitive_ports()
            severity = "critical" if exposed else "high"
            add(
                "internet_inbound",
                severity,
                "Inbound rule accepts traffic from the internet",
                (
                    f"'{rule.name}' allows inbound traffic from {rule.source_address} on "
                    f"port(s) {rule.destination_port}."
                    + (
                        f" This exposes {', '.join(SENSITIVE_PORTS[port] for port in exposed)} "
                        "directly to the internet."
                        if exposed
                        else ""
                    )
                ),
                {
                    "source": rule.source_address,
                    "port": rule.destination_port,
                    "sensitive_ports": [SENSITIVE_PORTS[port] for port in exposed],
                },
                (
                    "Restrict the source to known address ranges, or front the workload with "
                    "Azure Firewall, Application Gateway, or Bastion."
                ),
            )
            if exposed:
                add(
                    "sensitive_port_exposure",
                    "critical",
                    "Management or database port reachable from a broad source",
                    (
                        f"'{rule.name}' exposes {', '.join(SENSITIVE_PORTS[p] for p in exposed)} "
                        f"to {rule.source_address}."
                    ),
                    {
                        "ports": list(exposed),
                        "services": [SENSITIVE_PORTS[port] for port in exposed],
                        "source": rule.source_address,
                    },
                    "Remove direct exposure; use Bastion, a jump host, or Private Link instead.",
                )

        prefix_length = source.prefix_length
        if (
            rule.is_inbound
            and not source.is_internet
            and prefix_length is not None
            and prefix_length <= WIDE_PREFIX_THRESHOLD
        ):
            add(
                "wide_source_cidr",
                "medium",
                "Rule source spans an unusually wide address range",
                (
                    f"'{rule.name}' permits sources from {rule.source_address} "
                    f"(/{prefix_length}), covering a large portion of the address space."
                ),
                {"source": rule.source_address, "prefix_length": prefix_length},
                "Narrow the source to the specific subnets or application tiers that need access.",
            )

        if not ports.is_any and ports.cardinality > BROAD_PORT_THRESHOLD:
            add(
                "broad_port_range",
                "medium",
                "Rule opens an unusually large port range",
                (
                    f"'{rule.name}' opens {ports.cardinality} ports "
                    f"({rule.destination_port})."
                ),
                {"port_range": rule.destination_port, "port_count": ports.cardinality},
                "Limit the rule to the ports the application actually listens on.",
            )
        elif ports.is_any and not source.is_internet:
            add(
                "broad_port_range",
                "medium",
                "Rule opens all ports",
                f"'{rule.name}' uses '*' for the destination port range.",
                {"port_range": rule.destination_port, "port_count": 65536},
                "Enumerate the required ports instead of using '*'.",
            )

        if not _has_owner(rule.tags, rule.owner) and not _has_owner(nsg.tags, nsg.owner):
            add(
                "missing_owner",
                "low",
                "Rule has no identifiable owner",
                (
                    f"Neither '{rule.name}' nor its NSG '{nsg.name}' carries an owner tag, so "
                    "there is nobody to consult before tightening or removing it."
                ),
                {"nsg": nsg.name, "checked_tag_keys": list(OWNER_TAG_KEYS)},
                "Tag the NSG or rule with an owner or support team.",
            )

        return findings

    def _detect_shadowed(
        self, nsg: NetworkSecurityGroup, rules: list[NetworkSecurityRule]
    ) -> list[RuleFinding]:
        """A rule is shadowed when an earlier rule fully subsumes it.

        Only reported when subsumption is certain — unresolved service tags
        produce no finding rather than a false one.
        """
        findings: list[RuleFinding] = []
        for direction in ("Inbound", "Outbound"):
            ordered = [rule for rule in rules if rule.direction.casefold() == direction.casefold()]
            ordered.sort(key=lambda rule: rule.priority)
            for index, rule in enumerate(ordered):
                for earlier in ordered[:index]:
                    if not self._subsumes(earlier, rule):
                        continue
                    findings.append(
                        RuleFinding(
                            finding_id=_finding_id("shadowed", rule.resource_id),
                            category="shadowed",
                            severity="low" if earlier.access == rule.access else "high",
                            rule_id=rule.resource_id,
                            rule_name=rule.name,
                            control="nsg",
                            control_id=nsg.resource_id,
                            title="Rule is shadowed by a higher-priority rule",
                            detail=(
                                f"'{rule.name}' (priority {rule.priority}) can never be evaluated "
                                f"because '{earlier.name}' (priority {earlier.priority}) already "
                                f"matches every packet it would match and {earlier.access.lower()}s them."
                            ),
                            evidence={
                                "shadowing_rule": earlier.name,
                                "shadowing_priority": earlier.priority,
                                "shadowing_access": earlier.access,
                                "shadowed_priority": rule.priority,
                                "shadowed_access": rule.access,
                            },
                            recommendation=(
                                "Remove the shadowed rule, or raise its priority above the "
                                "rule that subsumes it if it was meant to take effect."
                            ),
                            connection_id=rule.connection_id or nsg.connection_id,
                            subscription_id=rule.subscription_id or nsg.subscription_id,
                            environment=rule.environment or nsg.environment,
                        )
                    )
                    break
        return findings

    def _subsumes(self, broad: NetworkSecurityRule, narrow: NetworkSecurityRule) -> bool:
        if not broad.protocol_spec.is_any and broad.protocol != narrow.protocol:
            return False
        if not self._spec_covers(broad.source_spec, narrow.source_spec):
            return False
        if not self._spec_covers(broad.destination_spec, narrow.destination_spec):
            return False
        broad_ports = broad.destination_port_spec
        narrow_ports = narrow.destination_port_spec
        if broad_ports.is_any:
            return True
        if narrow_ports.is_any:
            return False
        return all(
            any(low >= b_low and high <= b_high for b_low, b_high in broad_ports.ranges)
            for low, high in narrow_ports.ranges
        )

    def _spec_covers(self, broad: AddressSpec, narrow: AddressSpec) -> bool:
        if broad.is_any:
            return True
        if broad.service_tag or narrow.service_tag:
            return bool(broad.service_tag) and broad.service_tag == narrow.service_tag
        if narrow.is_any:
            return False
        return all(
            broad.contains_address(cidr) is True for cidr in narrow.networks
        )

    def _detect_unattached(self, nsg: NetworkSecurityGroup) -> list[RuleFinding]:
        """An NSG bound to nothing enforces nothing."""
        if nsg.subnet_ids or nsg.nic_ids:
            return []
        return [
            RuleFinding(
                finding_id=_finding_id("unused_nsg", nsg.resource_id),
                category="unused",
                severity="low",
                rule_id=nsg.resource_id,
                rule_name=nsg.name,
                control="nsg",
                control_id=nsg.resource_id,
                title="Network security group is not attached to any subnet or NIC",
                detail=(
                    f"'{nsg.name}' defines "
                    f"{len([r for r in nsg.rules if not r.is_default])} custom rule(s) but is not "
                    "associated with a subnet or network interface, so none of them take effect."
                ),
                evidence={
                    "custom_rule_count": len([r for r in nsg.rules if not r.is_default]),
                    "subnet_associations": 0,
                    "nic_associations": 0,
                    "basis": "association metadata; flow logs are not ingested",
                },
                recommendation="Attach the NSG where it is needed, or delete it.",
                connection_id=nsg.connection_id,
                subscription_id=nsg.subscription_id,
                environment=nsg.environment,
            )
        ]

    def _analyze_firewall_collection(
        self, collection: FirewallRuleCollection
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        if collection.action.casefold() != "allow":
            return findings

        for rule in collection.rules:
            findings.extend(self._analyze_firewall_rule(collection, rule))
        return findings

    def _analyze_firewall_rule(
        self, collection: FirewallRuleCollection, rule: FirewallRule
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        sources = rule.source_specs()
        destinations = rule.destination_specs()
        ports = rule.port_specs()

        def add(
            category: str,
            severity: str,
            title: str,
            detail: str,
            evidence: dict[str, Any],
            recommendation: str,
        ) -> None:
            findings.append(
                RuleFinding(
                    finding_id=_finding_id(category, rule.resource_id),
                    category=category,
                    severity=severity,
                    rule_id=rule.resource_id,
                    rule_name=rule.name,
                    control="azure_firewall",
                    control_id=collection.resource_id,
                    title=title,
                    detail=detail,
                    evidence=evidence,
                    recommendation=recommendation,
                    connection_id=rule.connection_id or collection.connection_id,
                    subscription_id=rule.subscription_id or collection.subscription_id,
                    environment=rule.environment or collection.environment,
                )
            )

        source_any = any(spec.is_any or spec.covers_all_addresses for spec in sources) or not sources
        dest_any = any(spec.is_any or spec.covers_all_addresses for spec in destinations) or not destinations
        ports_any = any(spec.is_any for spec in ports) or not ports

        if source_any and dest_any and ports_any:
            add(
                "any_any",
                "critical",
                "Firewall rule permits any source to any destination on any port",
                (
                    f"'{rule.name}' in collection '{collection.name}' "
                    f"(priority {collection.priority}) allows unrestricted traffic."
                ),
                {
                    "sources": list(rule.source_addresses),
                    "destinations": list(rule.destination_addresses),
                    "ports": list(rule.destination_ports),
                },
                "Scope the rule to specific sources, destinations, and ports.",
            )

        if source_any and not dest_any:
            add(
                "overly_broad",
                "high",
                "Firewall rule accepts any source",
                (
                    f"'{rule.name}' allows traffic from any source to "
                    f"{', '.join(rule.destination_addresses) or 'its destinations'}."
                ),
                {"sources": list(rule.source_addresses) or ["*"]},
                "Restrict the source addresses or use an IP group with a defined membership.",
            )

        exposed: list[int] = []
        for spec in ports:
            exposed.extend(spec.sensitive_ports())
        if exposed and source_any:
            unique = sorted(set(exposed))
            add(
                "sensitive_port_exposure",
                "critical",
                "Firewall rule exposes a sensitive port to any source",
                (
                    f"'{rule.name}' permits {', '.join(SENSITIVE_PORTS[p] for p in unique)} "
                    "from an unrestricted source."
                ),
                {"ports": unique, "services": [SENSITIVE_PORTS[p] for p in unique]},
                "Restrict the source, or move the access behind Bastion or Private Link.",
            )

        for spec in sources:
            length = spec.prefix_length
            if length is not None and length <= WIDE_PREFIX_THRESHOLD and not spec.covers_all_addresses:
                add(
                    "wide_source_cidr",
                    "medium",
                    "Firewall rule source spans a wide address range",
                    f"'{rule.name}' permits sources from {spec.raw} (/{length}).",
                    {"source": spec.raw, "prefix_length": length},
                    "Narrow the source range to the subnets that require the access.",
                )
                break

        if not _has_owner(rule.tags, rule.owner) and not _has_owner(
            collection.tags, collection.owner
        ):
            add(
                "missing_owner",
                "low",
                "Firewall rule has no identifiable owner",
                (
                    f"Neither '{rule.name}' nor collection '{collection.name}' carries an "
                    "owner tag."
                ),
                {"collection": collection.name, "checked_tag_keys": list(OWNER_TAG_KEYS)},
                "Tag the rule collection with an owner or support team.",
            )

        return findings


class CrossEnvironmentAnalyzer:
    """Detects rules that bridge non-production and production networks.

    Uses observed subnet address prefixes and their environment attribution,
    so a rule is only flagged when its addresses genuinely land in another
    environment's space — not merely because the names differ.
    """

    def __init__(self, snapshot: NetworkSnapshot) -> None:
        self.snapshot = snapshot
        self._environment_prefixes: dict[str, list[str]] = {}
        for subnet in snapshot.subnets:
            environment = _environment_class(subnet.environment)
            if environment == "unknown":
                continue
            self._environment_prefixes.setdefault(environment, []).extend(subnet.address_prefixes)

    def analyze(self) -> tuple[RuleFinding, ...]:
        findings: list[RuleFinding] = []
        production = self._environment_prefixes.get("production", [])
        non_production = self._environment_prefixes.get("non-production", [])
        if not production or not non_production:
            return ()

        for nsg in self.snapshot.nsgs:
            nsg_environment = _environment_class(nsg.environment)
            for rule in nsg.rules:
                if rule.is_default or not rule.is_allow:
                    continue
                finding = self._evaluate(nsg, rule, nsg_environment, production, non_production)
                if finding is not None:
                    findings.append(finding)
        return tuple(findings)

    def _evaluate(
        self,
        nsg: NetworkSecurityGroup,
        rule: NetworkSecurityRule,
        nsg_environment: str,
        production: list[str],
        non_production: list[str],
    ) -> RuleFinding | None:
        source = rule.source_spec
        destination = rule.destination_spec

        source_non_prod = self._touches(source, non_production)
        dest_prod = self._touches(destination, production)
        # Require positive evidence on both ends, or — for a rule sitting on a
        # production NSG, where the destination is implied — on the source.
        if not source_non_prod:
            return None
        if not dest_prod and not (nsg_environment == "production" and rule.is_inbound):
            return None

        return RuleFinding(
            finding_id=_finding_id("cross_environment", rule.resource_id),
            category="cross_environment",
            severity="high",
            rule_id=rule.resource_id,
            rule_name=rule.name,
            control="nsg",
            control_id=nsg.resource_id,
            title="Rule permits non-production to reach production",
            detail=(
                f"'{rule.name}' allows {rule.source_address} to reach {rule.destination_address} "
                f"on {rule.destination_port}. The source range overlaps non-production subnets "
                "and the destination overlaps production subnets."
            ),
            evidence={
                "source": rule.source_address,
                "destination": rule.destination_address,
                "port": rule.destination_port,
                "non_production_prefixes": non_production,
                "production_prefixes": production,
            },
            recommendation=(
                "Remove the cross-environment allowance, or route it through a controlled "
                "enforcement point with explicit approval."
            ),
            connection_id=rule.connection_id or nsg.connection_id,
            subscription_id=rule.subscription_id or nsg.subscription_id,
            environment=rule.environment or nsg.environment,
        )

    def _touches(self, spec: AddressSpec, prefixes: list[str]) -> bool:
        """Whether the spec demonstrably overlaps one of the given prefixes.

        A wildcard is deliberately *not* treated as evidence of a
        cross-environment bridge. ``*`` overlaps every environment, so
        accepting it would flag every broad rule as DEV-to-PROD reachability
        and bury the rules that genuinely bridge the two. Wildcard breadth is
        already reported by the ``any_any`` and ``internet_inbound``
        categories.
        """
        if spec.is_any or spec.service_tag:
            return False
        for prefix in prefixes:
            other = AddressSpec.parse(prefix)
            if spec.overlaps(other) is True:
                return True
        return False


#: Provenance marker written by ``flowlog_ingest`` on edges derived from a
#: real Traffic Analytics query. Fixture-derived edges carry ``"fixture"`` and
#: are deliberately ignored here: a curated fixture is not evidence about a
#: customer's estate, and a "this rule is never used" finding built on one
#: would be indefensible in a change review.
LIVE_FLOW_DATA_SOURCE = "traffic_analytics"

#: ``allowedVsObserved`` verdicts (set by ``flowlog_ingest._classify``).
#: A deny rule that blocked traffic is a *signal* (someone keeps trying); a
#: deny rule whose traffic was nonetheless observed as allowed is a
#: *contradiction* (another rule won, or the data conflicts) and is more
#: serious. They are counted separately rather than merged.
_VERDICT_DENIED_AND_BLOCKED = "denied_and_blocked"
_VERDICT_DENIED_BUT_ALLOWED = "denied_but_traffic_observed"


class ObservedTrafficAnalyzer:
    """Compares allow rules against traffic actually seen on the wire.

    Structural analysis can only say a rule is *unreachable*; it cannot say a
    reachable rule is *unused*. Flow logs close that gap, enabling two
    findings the other analyzers cannot make:

    * an allow rule that matched no observed flow -- a removal candidate;
    * a deny rule that traffic repeatedly hit -- either a misconfiguration
      breaking a legitimate caller, or something probing the estate.

    Safety property: with no live observations this analyzer returns nothing.
    "We saw no traffic" and "there was no traffic" are different claims, and
    only the second justifies a finding. Absent evidence, we stay silent
    rather than recommending someone delete a rule (D-05).
    """

    def __init__(
        self,
        snapshot: NetworkSnapshot,
        flow_observations: Sequence[Mapping[str, Any]],
        *,
        observation_window_days: int | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.observation_window_days = observation_window_days
        self._matched_rule_ids: set[str] = set()
        self._denied_attempts: dict[str, int] = {}
        self._deny_conflicts: dict[str, int] = {}
        self._has_live_data = False

        for edge in flow_observations:
            attributes = edge.get("attributes")
            attributes = attributes if isinstance(attributes, Mapping) else {}
            if attributes.get("dataSource") != LIVE_FLOW_DATA_SOURCE:
                continue
            self._has_live_data = True
            # Edges use "objectId" (see flowlog_ingest._add_edge); "object"
            # is accepted so a caller passing a simplified mapping still works.
            rule_id = str(edge.get("objectId") or edge.get("object") or "").strip().casefold()
            if not rule_id:
                continue
            self._matched_rule_ids.add(rule_id)
            verdict = attributes.get("allowedVsObserved")
            if verdict == _VERDICT_DENIED_AND_BLOCKED:
                self._denied_attempts[rule_id] = self._denied_attempts.get(rule_id, 0) + 1
            elif verdict == _VERDICT_DENIED_BUT_ALLOWED:
                self._deny_conflicts[rule_id] = self._deny_conflicts.get(rule_id, 0) + 1

    def analyze(self) -> tuple[RuleFinding, ...]:
        if not self._has_live_data:
            return ()

        findings: list[RuleFinding] = []
        for nsg in self.snapshot.nsgs:
            for rule in nsg.rules:
                if rule.is_default:
                    continue
                rule_key = rule.resource_id.strip().casefold()
                if rule.is_allow and rule_key not in self._matched_rule_ids:
                    findings.append(self._unobserved_allow(nsg, rule))
                attempts = self._denied_attempts.get(rule_key, 0)
                if attempts:
                    findings.append(self._denied_but_attempted(nsg, rule, attempts))
                conflicts = self._deny_conflicts.get(rule_key, 0)
                if conflicts:
                    findings.append(self._deny_conflict(nsg, rule, conflicts))
        return tuple(findings)

    def _window_text(self) -> str:
        if self.observation_window_days is None:
            return "the observed flow-log window"
        return f"the last {self.observation_window_days} day(s)"

    def _basis(self) -> str:
        return (
            "VNet flow logs via Traffic Analytics, joined to NSG rules; covers "
            f"{self._window_text()} only"
        )

    def _unobserved_allow(
        self, nsg: NetworkSecurityGroup, rule: NetworkSecurityRule
    ) -> RuleFinding:
        return RuleFinding(
            finding_id=_finding_id("unobserved_allow_rule", rule.resource_id),
            # Deliberately NOT "unused": that category means *structurally
            # unreachable*, proven from configuration alone. This one means
            # "reachable, but no traffic was seen in a bounded window" -- a
            # weaker, time-limited claim. Merging them would let a reviewer
            # mistake observational absence for structural proof.
            category="observed_traffic",
            severity="low",
            rule_id=rule.resource_id,
            rule_name=rule.name,
            control="nsg",
            control_id=nsg.resource_id,
            title="Allow rule permits traffic that was never observed",
            detail=(
                f"Rule '{rule.name}' on '{nsg.name}' permits "
                f"{rule.protocol} {rule.source_address} -> {rule.destination_address}:"
                f"{rule.destination_port}, but no flow matching it was seen during "
                f"{self._window_text()}. It is a removal candidate."
            ),
            evidence={
                "direction": rule.direction,
                "protocol": rule.protocol,
                "source_address": rule.source_address,
                "destination_address": rule.destination_address,
                "destination_port": rule.destination_port,
                "observed_flow_count": 0,
                "observation_window_days": self.observation_window_days,
                "basis": self._basis(),
            },
            recommendation=(
                "Confirm the rule is not needed for a periodic or seasonal workload that "
                "falls outside the observation window, then remove it."
            ),
            connection_id=nsg.connection_id,
            subscription_id=nsg.subscription_id,
            environment=nsg.environment,
        )

    def _denied_but_attempted(
        self, nsg: NetworkSecurityGroup, rule: NetworkSecurityRule, attempts: int
    ) -> RuleFinding:
        return RuleFinding(
            finding_id=_finding_id("denied_traffic_attempted", rule.resource_id),
            category="observed_traffic",
            severity="medium",
            rule_id=rule.resource_id,
            rule_name=rule.name,
            control="nsg",
            control_id=nsg.resource_id,
            title="Deny rule is being hit by repeated traffic",
            detail=(
                f"Rule '{rule.name}' on '{nsg.name}' denied {attempts} distinct observed "
                f"flow(s) during {self._window_text()}. Either a legitimate caller is "
                "misconfigured, or something is probing this path."
            ),
            evidence={
                "direction": rule.direction,
                "protocol": rule.protocol,
                "source_address": rule.source_address,
                "destination_address": rule.destination_address,
                "destination_port": rule.destination_port,
                "denied_flow_count": attempts,
                "observation_window_days": self.observation_window_days,
                "basis": self._basis(),
            },
            recommendation=(
                "Identify the source. If it is a legitimate dependency, allow it explicitly "
                "and narrowly; otherwise treat the attempts as a security signal."
            ),
            connection_id=nsg.connection_id,
            subscription_id=nsg.subscription_id,
            environment=nsg.environment,
        )

    def _deny_conflict(
        self, nsg: NetworkSecurityGroup, rule: NetworkSecurityRule, conflicts: int
    ) -> RuleFinding:
        """A deny rule matched a flow that was nonetheless permitted.

        This is a contradiction, not merely a signal: either a
        higher-priority allow rule is winning (so this deny is not doing what
        its author believed), or the flow data disagrees with the
        configuration. Both warrant investigation, and neither is safely
        resolved by assuming one side is right (D-05).
        """
        return RuleFinding(
            finding_id=_finding_id("deny_rule_conflict", rule.resource_id),
            category="observed_traffic",
            severity="high",
            rule_id=rule.resource_id,
            rule_name=rule.name,
            control="nsg",
            control_id=nsg.resource_id,
            title="Traffic matching a deny rule was observed as allowed",
            detail=(
                f"Rule '{rule.name}' on '{nsg.name}' denies "
                f"{rule.protocol} {rule.source_address} -> {rule.destination_address}:"
                f"{rule.destination_port}, yet {conflicts} observed flow(s) matching it "
                f"were permitted during {self._window_text()}. A higher-priority allow "
                "rule is most likely overriding it."
            ),
            evidence={
                "direction": rule.direction,
                "priority": rule.priority,
                "protocol": rule.protocol,
                "source_address": rule.source_address,
                "destination_address": rule.destination_address,
                "destination_port": rule.destination_port,
                "conflicting_flow_count": conflicts,
                "observation_window_days": self.observation_window_days,
                "basis": self._basis(),
            },
            recommendation=(
                "Compare against higher-priority allow rules on the same NSG. Either raise "
                "this rule's priority or narrow the allow rule that overrides it."
            ),
            connection_id=nsg.connection_id,
            subscription_id=nsg.subscription_id,
            environment=nsg.environment,
        )


def analyze_rules(
    snapshot: NetworkSnapshot,
    flow_observations: Sequence[Mapping[str, Any]] | None = None,
    *,
    observation_window_days: int | None = None,
) -> tuple[RuleFinding, ...]:
    """Runs every rule analyzer and returns the merged, severity-sorted findings.

    ``flow_observations`` are the ``trafficObserved`` edges produced by
    ``fabric_pipelines.flowlog_ingest.join_flow_logs_with_nsg_rules``. When
    omitted (or when they carry no live traffic), the observed-traffic
    analyzer contributes nothing -- silence, not a false "never used" claim.
    """
    findings = list(RuleTighteningAnalyzer(snapshot).analyze())
    findings.extend(CrossEnvironmentAnalyzer(snapshot).analyze())
    findings.extend(
        ObservedTrafficAnalyzer(
            snapshot,
            flow_observations or (),
            observation_window_days=observation_window_days,
        ).analyze()
    )
    return tuple(
        sorted(
            findings,
            key=lambda item: (SEVERITY_ORDER.get(item.severity, 9), item.category, item.rule_id),
        )
    )
