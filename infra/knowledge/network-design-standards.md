# Network Design Standards

## Hub-and-spoke segmentation
- Spoke VNets must never peer directly with each other; all inter-spoke and
  spoke-to-internet traffic routes through the hub firewall.
- Every spoke must have a default route (0.0.0.0/0) pointed at the hub
  firewall's private IP via a User Defined Route (UDR) on every subnet except
  the AzureFirewallSubnet/GatewaySubnet themselves.
- Production and non-production workloads must not share a spoke VNet.

## Firewall rule hygiene
- Application rules should reference FQDN tags or explicit FQDNs, not wildcard
  `*.` patterns, except for well-known Microsoft service tags.
- Network rules must specify explicit source/destination CIDRs and ports —
  `Any`/`*` source or destination is a policy violation unless documented
  with an approved exception and expiry date.
- Every rule collection must carry a `priority` that leaves at least 100 units
  of headroom from adjacent collections, so a new rule can be inserted between
  two existing ones without renumbering.
- Deny-by-default: the last rule collection in every policy must be an
  explicit deny-all: a firewall with no explicit deny relies on Azure
  Firewall's implicit deny, which is easy to defeat if a rule is later loosened.

## NSG standards
- Every subnet must have an NSG attached; relying solely on the firewall for
  east-west segmentation is not sufficient because it does not see
  intra-VNet traffic that never traverses the hub.
- NSG rules must be scoped to service tags or specific CIDRs; `Internet` as a
  source on any inbound rule other than a documented public-facing ingress
  point is a design violation.
- Rule priorities 100-4096 are reserved for explicit organization rules; do
  not rely on the default allow-VNet-inbound/deny-Internet-inbound rules for
  documentation purposes — write explicit rules stating intent.

## Private connectivity
- PaaS services accessed from within the VNet (Storage, Key Vault, SQL,
  Cognitive Services) must use Private Endpoints, not service endpoints,
  for any resource holding production or confidential data.
- Private DNS zones for Private Endpoints must be linked to every VNet that
  needs to resolve them, including the hub if hub-based resources call the
  service.
