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
from dataclasses import dataclass
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
    source_path: str = ""

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
