"""Network address primitives.

Deliberately dependency-free (no ``ipaddress`` reliance for the hot path) so
rule evaluation stays deterministic across CIDR notation, service tags, and
Azure's shorthand wildcards (``*``, ``Any``, ``Internet``, ``VirtualNetwork``).
A rule that names a service tag is *not* silently treated as an address range:
tags are compared by name, and an unresolvable tag is reported as unknown
rather than assumed to match.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

#: Azure service tags that carry topology meaning for reachability analysis.
INTERNET_TAGS = frozenset({"internet"})
ANY_TOKENS = frozenset({"*", "any", ""})
VIRTUAL_NETWORK_TAGS = frozenset({"virtualnetwork", "vnet"})

#: Ports that carry elevated exposure risk when reachable from broad sources.
SENSITIVE_PORTS: dict[int, str] = {
    22: "SSH",
    3389: "RDP",
    1433: "SQL Server",
    3306: "MySQL",
    5432: "PostgreSQL",
    1521: "Oracle",
    27017: "MongoDB",
    6379: "Redis",
    9200: "Elasticsearch",
    445: "SMB",
    135: "RPC",
    5985: "WinRM",
    5986: "WinRM (TLS)",
}


def normalize_token(value: Any) -> str:
    """Casefolds and trims an address/port/protocol token."""
    return str(value or "").strip().casefold()


@dataclass(frozen=True)
class AddressSpec:
    """A rule's source or destination address expression.

    Exactly one interpretation applies: a set of CIDR networks, a service tag,
    or the ``any`` wildcard. Keeping them distinct is what allows the analyzer
    to say "this rule is broad because it uses ``*``" separately from "this
    rule is broad because it uses ``0.0.0.0/0``".
    """

    raw: str
    networks: tuple[str, ...] = ()
    service_tag: str = ""
    is_any: bool = False

    @classmethod
    def parse(cls, value: Any) -> AddressSpec:
        token = normalize_token(value)
        if token in ANY_TOKENS:
            return cls(raw=str(value or "*"), is_any=True)
        try:
            network = ipaddress.ip_network(token, strict=False)
        except ValueError:
            return cls(raw=str(value), service_tag=token)
        return cls(raw=str(value), networks=(str(network),))

    @property
    def is_internet(self) -> bool:
        return self.is_any or self.service_tag in INTERNET_TAGS or self.covers_all_addresses

    @property
    def is_virtual_network(self) -> bool:
        return self.service_tag in VIRTUAL_NETWORK_TAGS

    @property
    def covers_all_addresses(self) -> bool:
        """True when the spec spans the whole address space (``0.0.0.0/0``)."""
        if self.is_any:
            return True
        for cidr in self.networks:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if network.prefixlen == 0:
                return True
        return False

    @property
    def prefix_length(self) -> int | None:
        """Smallest prefix length across the spec's networks (``None`` for tags)."""
        lengths = []
        for cidr in self.networks:
            try:
                lengths.append(ipaddress.ip_network(cidr, strict=False).prefixlen)
            except ValueError:
                continue
        return min(lengths) if lengths else None

    def contains_address(self, address: str) -> bool | None:
        """Whether ``address`` falls inside this spec.

        Returns ``None`` when undecidable — an unresolved service tag. Callers
        must treat ``None`` as "unknown", never as a match or a non-match.
        """
        if self.is_any:
            return True
        if self.service_tag:
            return None
        try:
            candidate = ipaddress.ip_address(normalize_token(address))
        except ValueError:
            try:
                candidate_net = ipaddress.ip_network(normalize_token(address), strict=False)
            except ValueError:
                return None
            return any(
                candidate_net.subnet_of(ipaddress.ip_network(cidr, strict=False))
                for cidr in self.networks
                if _same_family(cidr, candidate_net)
            )
        return any(
            candidate in ipaddress.ip_network(cidr, strict=False)
            for cidr in self.networks
            if _same_family(cidr, candidate)
        )

    def overlaps(self, other: AddressSpec) -> bool | None:
        """Whether two specs can describe an overlapping address set."""
        if self.is_any or other.is_any:
            return True
        if self.service_tag or other.service_tag:
            if self.service_tag and other.service_tag:
                return self.service_tag == other.service_tag
            return None
        for left in self.networks:
            for right in other.networks:
                try:
                    left_net = ipaddress.ip_network(left, strict=False)
                    right_net = ipaddress.ip_network(right, strict=False)
                except ValueError:
                    continue
                if left_net.version == right_net.version and left_net.overlaps(right_net):
                    return True
        return False


def _same_family(cidr: str, other: Any) -> bool:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    return network.version == getattr(other, "version", network.version)


@dataclass(frozen=True)
class PortSpec:
    """A rule's port expression: ``*``, a single port, or ranges."""

    raw: str
    ranges: tuple[tuple[int, int], ...] = ()
    is_any: bool = False

    @classmethod
    def parse(cls, value: Any) -> PortSpec:
        token = normalize_token(value)
        if token in ANY_TOKENS:
            return cls(raw=str(value or "*"), is_any=True)
        ranges: list[tuple[int, int]] = []
        for part in token.replace(";", ",").split(","):
            piece = part.strip()
            if not piece:
                continue
            if "-" in piece:
                low, _, high = piece.partition("-")
                try:
                    ranges.append((int(low), int(high)))
                except ValueError:
                    continue
            else:
                try:
                    port = int(piece)
                except ValueError:
                    continue
                ranges.append((port, port))
        if not ranges:
            return cls(raw=str(value), is_any=False)
        return cls(raw=str(value), ranges=tuple(sorted(ranges)))

    def contains(self, port: int | None) -> bool:
        if self.is_any:
            return True
        if port is None:
            return False
        return any(low <= port <= high for low, high in self.ranges)

    @property
    def cardinality(self) -> int:
        """Number of ports the spec admits; 65536 for ``*``."""
        if self.is_any:
            return 65536
        return sum(high - low + 1 for low, high in self.ranges)

    def sensitive_ports(self) -> tuple[int, ...]:
        """Sensitive ports this spec exposes (all of them when ``*``)."""
        if self.is_any:
            return tuple(sorted(SENSITIVE_PORTS))
        return tuple(sorted(port for port in SENSITIVE_PORTS if self.contains(port)))


@dataclass(frozen=True)
class ProtocolSpec:
    """A rule's protocol expression."""

    raw: str
    protocol: str = "*"

    @classmethod
    def parse(cls, value: Any) -> ProtocolSpec:
        token = normalize_token(value)
        if token in ANY_TOKENS:
            return cls(raw=str(value or "*"), protocol="*")
        return cls(raw=str(value), protocol=token)

    @property
    def is_any(self) -> bool:
        return self.protocol == "*"

    def matches(self, protocol: str) -> bool:
        candidate = normalize_token(protocol)
        if self.is_any or candidate in ANY_TOKENS:
            return True
        return self.protocol == candidate
