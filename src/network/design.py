"""Customer-defined hub-spoke design policy.

The platform cannot infer what a customer *intended*; it can only observe
what exists. This module lets an architect declare the approved common
services design so observed topology can be compared against it.

Policies are loaded from YAML/JSON. An absent policy is not an error — the
design-validation results simply report that no intended design was declared,
which is materially different from "the design is satisfied".
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_POLICY_FILENAMES = (
    "network-design.yaml",
    "network-design.yml",
    "network_design.yaml",
    "network-design.json",
)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    return ()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes", "on"}


#: Built-in rule identifiers. Kept as constants so gap-analysis code and the
#: API/UI agree on a stable id regardless of how a customer edits the name
#: or description of the rule.
RULE_INTERNET_VIA_FIREWALL = "internet-via-firewall"
RULE_NSG_OVERRIDE_DEFAULT_OUTBOUND = "nsg-override-default-outbound"
RULE_PRIVATE_ENDPOINTS_PREFERRED = "private-endpoints-preferred"
RULE_NSG_ON_EVERY_SUBNET = "nsg-on-every-subnet"
RULE_APPROVED_PEERINGS_ONLY = "approved-peerings-only"
RULE_BIDIRECTIONAL_PEERING = "bidirectional-peering"
RULE_PRIVATE_DNS_ZONE_LINK = "private-dns-zone-link"
RULE_NO_ORPHAN_FIREWALL_RULES = "no-orphan-firewall-rules"
RULE_DOCUMENTED_DEPENDENCIES = "documented-dependencies"
RULE_HUB_FIREWALL_PRESENT = "hub-firewall-present"


@dataclass(frozen=True)
class PolicyRule:
    """A single, independently toggleable enforcement rule.

    The rule list is the extensibility seam: new rules are added here (and a
    matching check in ``gaps.py`` or ``tightening.py``) without changing the
    document schema, so the UI can list, enable/disable, and edit any rule
    generically instead of the backend hard-coding one boolean field per
    rule.
    """

    rule_id: str
    name: str
    description: str = ""
    category: str = "custom"
    severity: str = "high"
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "enabled": self.enabled,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> PolicyRule | None:
        if not isinstance(value, dict):
            return None
        rule_id = str(value.get("rule_id") or value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not rule_id or not name:
            return None
        parameters = value.get("parameters")
        return cls(
            rule_id=rule_id,
            name=name,
            description=str(value.get("description") or "").strip(),
            category=str(value.get("category") or "custom").strip() or "custom",
            severity=str(value.get("severity") or "high").strip() or "high",
            enabled=_bool(value.get("enabled"), True),
            parameters=dict(parameters) if isinstance(parameters, dict) else {},
        )


def default_policy_rules() -> tuple[PolicyRule, ...]:
    """The rules a fresh design policy starts with.

    Both encode a customer's stated intent so the seeding here is only a
    starting point -- every field remains editable through the policy API,
    and additional rules can be appended without touching this shape.
    """
    return (
        PolicyRule(
            rule_id=RULE_INTERNET_VIA_FIREWALL,
            name="Internet access must traverse the firewall",
            description=(
                "Every spoke subnet's default route (0.0.0.0/0) must send traffic to the "
                "hub firewall's private IP. A subnet with no route table, no default "
                "route, or a default route to anything else can reach the internet "
                "directly, bypassing inspection."
            ),
            category="egress_control",
            severity="high",
            enabled=True,
        ),
        PolicyRule(
            rule_id=RULE_NSG_OVERRIDE_DEFAULT_OUTBOUND,
            name="NSGs must override the default allow-internet-outbound rule",
            description=(
                "Every NSG must carry an explicit outbound rule, at a priority lower than "
                "Azure's default AllowInternetOutBound rule (65001), that governs traffic to "
                "the internet -- so egress is a deliberate, reviewed decision rather than "
                "Azure's silent default allow."
            ),
            category="nsg_hardening",
            severity="high",
            enabled=True,
        ),
    )


@dataclass(frozen=True)
class ApprovedPeering:
    """A peering the design permits, expressed by VNet name pattern."""

    source: str
    target: str
    bidirectional: bool = True

    def matches(self, left_name: str, right_name: str) -> bool:
        pair = {str(left_name or "").casefold(), str(right_name or "").casefold()}
        declared = {self.source.casefold(), self.target.casefold()}
        if self.bidirectional:
            return pair == declared
        return (
            str(left_name or "").casefold() == self.source.casefold()
            and str(right_name or "").casefold() == self.target.casefold()
        )


@dataclass(frozen=True)
class NetworkDesignPolicy:
    """The approved hub-spoke design a customer wants enforced."""

    name: str = ""
    description: str = ""
    hub_vnet_names: tuple[str, ...] = ()
    require_firewall_in_hub: bool = True
    require_default_route_to_firewall: bool = True
    require_nsg_on_every_subnet: bool = True
    forbid_spoke_to_spoke_peering: bool = True
    forbid_public_ip_on_spoke_nics: bool = True
    require_private_endpoint_for_services: tuple[str, ...] = ()
    require_private_dns_zone_link: bool = True
    require_bidirectional_peering: bool = True
    approved_peerings: tuple[ApprovedPeering, ...] = ()
    exempt_subnet_names: tuple[str, ...] = (
        "gatewaysubnet",
        "azurefirewallsubnet",
        "azurebastionsubnet",
        "routeserversubnet",
    )
    exempt_vnet_names: tuple[str, ...] = ()
    #: Extensible, user-editable enforcement rules (starts with the two
    #: rules the customer asked for: internet-via-firewall and NSG override
    #: of the default outbound-allow rule). Additional rules append here.
    rules: tuple[PolicyRule, ...] = field(default_factory=default_policy_rules)
    #: Tracks whether the policy document explicitly supplied a rule list.
    #: Default seed rules alone do not constitute a declared design.
    rules_declared: bool = False
    source_path: str = ""

    def rule(self, rule_id: str) -> PolicyRule | None:
        return next((item for item in self.rules if item.rule_id == rule_id), None)

    def rule_enabled(self, rule_id: str, *, default: bool = True) -> bool:
        """Whether a named rule is enabled, defaulting on if never declared."""
        found = self.rule(rule_id)
        return found.enabled if found is not None else default

    @property
    def is_declared(self) -> bool:
        """Whether a customer actually expressed an intended design.

        Keyed on declared content rather than on ``source_path`` so a policy
        supplied programmatically (tests, an API request, a future UI) counts
        the same as one loaded from disk. When this is False, every gap must
        state that no intended design was declared.
        """
        return bool(
            self.source_path
            or self.name
            or self.hub_vnet_names
            or self.approved_peerings
            or self.require_private_endpoint_for_services
            or self.exempt_vnet_names
            or self.rules_declared
            or self.rules != default_policy_rules()
        )

    def is_exempt_subnet(self, name: str) -> bool:
        return str(name or "").casefold() in {
            value.casefold() for value in self.exempt_subnet_names
        }

    def is_exempt_vnet(self, name: str) -> bool:
        return str(name or "").casefold() in {
            value.casefold() for value in self.exempt_vnet_names
        }

    def declares_hub(self, name: str) -> bool:
        return str(name or "").casefold() in {
            value.casefold() for value in self.hub_vnet_names
        }

    def peering_is_approved(self, left_name: str, right_name: str) -> bool:
        if not self.approved_peerings:
            return True
        return any(
            approved.matches(left_name, right_name) for approved in self.approved_peerings
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "is_declared": self.is_declared,
            "source_path": self.source_path,
            "hub_vnet_names": list(self.hub_vnet_names),
            "require_firewall_in_hub": self.require_firewall_in_hub,
            "require_default_route_to_firewall": self.require_default_route_to_firewall,
            "require_nsg_on_every_subnet": self.require_nsg_on_every_subnet,
            "forbid_spoke_to_spoke_peering": self.forbid_spoke_to_spoke_peering,
            "forbid_public_ip_on_spoke_nics": self.forbid_public_ip_on_spoke_nics,
            "require_private_endpoint_for_services": list(
                self.require_private_endpoint_for_services
            ),
            "require_private_dns_zone_link": self.require_private_dns_zone_link,
            "require_bidirectional_peering": self.require_bidirectional_peering,
            "approved_peerings": [
                {
                    "source": item.source,
                    "target": item.target,
                    "bidirectional": item.bidirectional,
                }
                for item in self.approved_peerings
            ],
            "exempt_subnet_names": list(self.exempt_subnet_names),
            "exempt_vnet_names": list(self.exempt_vnet_names),
            "rules": [item.to_dict() for item in self.rules],
            "rules_declared": self.rules_declared,
        }

    @classmethod
    def from_mapping(cls, value: Any, *, source_path: str = "") -> NetworkDesignPolicy:
        if not isinstance(value, dict):
            return cls(source_path=source_path)
        data = value.get("network_design") if isinstance(value.get("network_design"), dict) else value

        peerings: list[ApprovedPeering] = []
        for item in data.get("approved_peerings") or []:
            if isinstance(item, dict):
                source = str(item.get("source") or item.get("from") or "").strip()
                target = str(item.get("target") or item.get("to") or "").strip()
                if source and target:
                    peerings.append(
                        ApprovedPeering(
                            source=source,
                            target=target,
                            bidirectional=_bool(item.get("bidirectional"), True),
                        )
                    )

        defaults = cls()

        rules_by_id: dict[str, PolicyRule] = {rule.rule_id: rule for rule in defaults.rules}
        for item in data.get("rules") or []:
            parsed = PolicyRule.from_mapping(item)
            if parsed is not None:
                rules_by_id[parsed.rule_id] = parsed

        return cls(
            name=str(data.get("name") or "").strip(),
            description=str(data.get("description") or "").strip(),
            hub_vnet_names=_strings(
                data.get("hub_vnet_names") or data.get("hub_vnets") or data.get("hubs")
            ),
            require_firewall_in_hub=_bool(
                data.get("require_firewall_in_hub"), defaults.require_firewall_in_hub
            ),
            require_default_route_to_firewall=_bool(
                data.get("require_default_route_to_firewall"),
                defaults.require_default_route_to_firewall,
            ),
            require_nsg_on_every_subnet=_bool(
                data.get("require_nsg_on_every_subnet"), defaults.require_nsg_on_every_subnet
            ),
            forbid_spoke_to_spoke_peering=_bool(
                data.get("forbid_spoke_to_spoke_peering"), defaults.forbid_spoke_to_spoke_peering
            ),
            forbid_public_ip_on_spoke_nics=_bool(
                data.get("forbid_public_ip_on_spoke_nics"), defaults.forbid_public_ip_on_spoke_nics
            ),
            require_private_endpoint_for_services=_strings(
                data.get("require_private_endpoint_for_services")
            ),
            require_private_dns_zone_link=_bool(
                data.get("require_private_dns_zone_link"), defaults.require_private_dns_zone_link
            ),
            require_bidirectional_peering=_bool(
                data.get("require_bidirectional_peering"), defaults.require_bidirectional_peering
            ),
            approved_peerings=tuple(peerings),
            exempt_subnet_names=_strings(data.get("exempt_subnet_names"))
            or defaults.exempt_subnet_names,
            exempt_vnet_names=_strings(data.get("exempt_vnet_names")),
            rules=tuple(rules_by_id.values()),
            rules_declared="rules" in data,
            source_path=source_path,
        )


def load_design_policy(path: str | Path | None = None) -> NetworkDesignPolicy:
    """Loads a design policy, returning an undeclared policy when absent.

    Never raises for a missing file: an estate with no declared design is a
    normal and reportable state.
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        cwd = Path.cwd()
        for name in DEFAULT_POLICY_FILENAMES:
            candidates.extend([cwd / name, cwd / "config" / name])

    for candidate in candidates:
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8")
        data = _parse(text, candidate)
        return NetworkDesignPolicy.from_mapping(data, source_path=str(candidate))

    return NetworkDesignPolicy()


def _parse(text: str, path: Path) -> Any:
    if path.suffix.casefold() == ".json":
        return json.loads(text)
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is a declared dependency
        return json.loads(text)
    return yaml.safe_load(text)


#: Persisted policy document name, following the same convention as
#: ``state/enterprise_settings.json``.
POLICY_DOCUMENT = "state/network_design_policy.json"


class NetworkDesignPolicyValidationError(ValueError):
    """Raised when a policy update would leave the policy unusable."""


class NetworkDesignPolicyRevisionConflict(RuntimeError):
    """Raised when a policy writer targets a superseded revision."""

    def __init__(self, expected: int, current: int) -> None:
        self.expected = expected
        self.current = current
        super().__init__(
            f"Network design policy revision {current} does not match "
            f"expected {expected}; reload and retry"
        )


def validate_policy_update(changes: dict[str, Any]) -> None:
    """Rejects a subset of malformed edits before they are ever persisted.

    Anything shaped like a policy (dict) is accepted; ``from_mapping`` already
    defaults every unrecognized or missing field, so validation here only
    needs to catch structurally broken input a UI form should never submit.
    """
    if not isinstance(changes, dict):
        raise NetworkDesignPolicyValidationError("Policy update must be a JSON object")
    rules = changes.get("rules")
    if rules is not None:
        if not isinstance(rules, list):
            raise NetworkDesignPolicyValidationError("rules must be a list")
        seen: set[str] = set()
        for item in rules:
            if not isinstance(item, dict):
                raise NetworkDesignPolicyValidationError("Each rule must be an object")
            rule_id = str(item.get("rule_id") or item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not rule_id or not name:
                raise NetworkDesignPolicyValidationError(
                    "Each rule requires a rule_id and a name"
                )
            if rule_id in seen:
                raise NetworkDesignPolicyValidationError(f"Duplicate rule_id: {rule_id}")
            seen.add(rule_id)
    remove_ids = changes.get("remove_rule_ids")
    if remove_ids is not None and not isinstance(remove_ids, list):
        raise NetworkDesignPolicyValidationError("remove_rule_ids must be a list")


class NetworkDesignPolicyStore:
    """Reads and writes the UI-editable network design policy document.

    Same shape as :class:`~intelligence.governance.settings.EnterpriseSettingsStore`:
    a single revision-checked document, defaulted on read, validated on
    write, with an in-memory fallback when no document store is configured
    (correct for a single-process local run, never reached in a deployed
    replica with OneLake configured).
    """

    def __init__(
        self,
        documents: Any = None,
        *,
        revision_cache_seconds: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if revision_cache_seconds < 0:
            raise ValueError("revision_cache_seconds cannot be negative")
        self._documents = documents
        self._memory: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._revision_cache_seconds = revision_cache_seconds
        self._monotonic = monotonic
        self._cached_revision: int | None = None
        self._revision_checked_at = float("-inf")

    def read(self) -> NetworkDesignPolicy:
        with self._lock:
            payload = self._read_document()
        stored = payload.get("policy")
        return NetworkDesignPolicy.from_mapping(stored if isinstance(stored, dict) else {})

    def read_with_revision_or_raise(
        self,
    ) -> tuple[NetworkDesignPolicy, int]:
        """Read one authoritative policy document and its matching revision.

        Provider construction must not combine a strict revision probe with a
        second fail-open body read: that can publish the default policy as
        healthy when OneLake fails between those operations.
        """
        with self._lock:
            payload = self._read_document(strict=True)
            revision = int(payload.get("revision") or 0)
            stored = payload.get("policy")
            policy = NetworkDesignPolicy.from_mapping(
                stored if isinstance(stored, dict) else {}
            )
            self._cached_revision = revision
            self._revision_checked_at = self._monotonic()
            return policy, revision

    @property
    def revision(self) -> int:
        """Return the last known revision, preserving the fail-open read API."""
        try:
            return self.revision_or_raise()
        # Credential and transport SDKs do not share one stable exception
        # base; this compatibility accessor must preserve the last known key.
        except Exception:  # noqa: BLE001
            with self._lock:
                return (
                    self._cached_revision
                    if self._cached_revision is not None
                    else 0
                )

    def revision_or_raise(self) -> int:
        """Return a short-lived revision, surfacing store read failures."""
        with self._lock:
            now = self._monotonic()
            if (
                self._cached_revision is not None
                and now - self._revision_checked_at
                < self._revision_cache_seconds
            ):
                return self._cached_revision
            revision = int(
                self._read_document(strict=True).get("revision") or 0
            )
            self._cached_revision = revision
            self._revision_checked_at = now
            return revision

    def update(
        self,
        changes: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> NetworkDesignPolicy:
        """Applies a partial update and returns the full effective policy."""
        validate_policy_update(changes)
        with self._lock:
            payload = self._read_document()
            revision = int(payload.get("revision") or 0)
            if expected_revision is not None and expected_revision != revision:
                raise NetworkDesignPolicyRevisionConflict(
                    expected_revision,
                    revision,
                )
            stored = payload.get("policy")
            current = NetworkDesignPolicy.from_mapping(
                stored if isinstance(stored, dict) else {}
            )
            merged = self._merge_changes(changes, current=current)
            document = {"policy": merged, "revision": revision + 1}
            if self._documents is None:
                self._memory = document
            else:
                self._documents.write(
                    POLICY_DOCUMENT,
                    document,
                    expected_revision=revision,
                )
            self._cached_revision = revision + 1
            self._revision_checked_at = self._monotonic()
        return NetworkDesignPolicy.from_mapping(merged)

    def preview(self, changes: dict[str, Any]) -> NetworkDesignPolicy:
        """Returns the effective policy for changes without persisting them."""
        validate_policy_update(changes)
        with self._lock:
            return NetworkDesignPolicy.from_mapping(self._merge_changes(changes))

    def _read_document(self, *, strict: bool = False) -> dict[str, Any]:
        if self._documents is None:
            return self._memory
        if strict:
            strict_reader = getattr(self._documents, "read_or_raise", None)
            if callable(strict_reader):
                return strict_reader(POLICY_DOCUMENT)
        return self._documents.read(POLICY_DOCUMENT)

    def _merge_changes(
        self,
        changes: dict[str, Any],
        *,
        current: NetworkDesignPolicy | None = None,
    ) -> dict[str, Any]:
        current_payload = (current or self.read()).to_dict()
        merged = {**current_payload, **changes}
        # Rules replace by rule_id rather than requiring the whole list to be
        # resubmitted, so a UI toggling one rule's ``enabled`` flag does not
        # need to round-trip every other rule first.
        if "rules" in changes:
            existing_rules = {
                item["rule_id"]: item for item in current_payload.get("rules") or []
            }
            for item in changes["rules"]:
                if isinstance(item, dict) and item.get("rule_id"):
                    existing_rules[str(item["rule_id"])] = item
            merged["rules"] = list(existing_rules.values())
        # ``remove_rule_ids`` is a write-only instruction, not a policy field:
        # it deletes rules by id (e.g. a custom rule an architect added and
        # later wants removed) and must never be persisted itself.
        remove_ids = changes.get("remove_rule_ids")
        if remove_ids:
            to_remove = {str(item) for item in remove_ids}
            merged["rules"] = [
                item
                for item in merged.get("rules") or []
                if str(item.get("rule_id")) not in to_remove
            ]
        merged.pop("remove_rule_ids", None)
        return merged
