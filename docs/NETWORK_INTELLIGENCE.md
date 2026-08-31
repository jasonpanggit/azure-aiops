# Network Topology and Traffic-Flow Validation

## Scope and boundary

This slice answers whether the **actual** network configuration matches the
**intended** hub-and-spoke design. It is read-only and configuration-derived:
Azure Resource Graph is the only source, and the engine never calls the Azure
control plane, never mutates a rule, and never reads flow logs.

That last point is load-bearing. Every conclusion here describes **what the
rules permit**, not **what traffic occurred**. Findings state this in their own
`basis` field so a reader is never left to assume otherwise.

## Architecture

```mermaid
flowchart LR
  ARG[ARG microsoft.network/*] --> NORM[network_normalize]
  NORM --> ONT[Ontology entities and relationships]
  ONT --> LOAD[NetworkSnapshotLoader]
  LOAD --> TOP[TopologyBuilder]
  LOAD --> FLOW[TrafficFlowValidator]
  LOAD --> TIGHT[Rule tightening analyzer]
  TOP --> GAPS[NetworkGapAnalyzer]
  POLICY[Design policy YAML] --> GAPS
  TOP --> SVC[NetworkIntelligenceService]
  FLOW --> SVC
  TIGHT --> SVC
  GAPS --> SVC
  SVC --> API[/api/v1/network/*]
  ONT --> SEM[Semantic Knowledge Layer]
  API --> UI[Operations Workbench]
```

## Data model

Sixteen entity types are ingested and registered in the ontology: `VNet`,
`Subnet`, `NetworkInterface`, `NetworkSecurityGroup`, `NetworkSecurityRule`,
`RouteTable`, `Route`, `VNetPeering`, `AzureFirewall`, `FirewallPolicy`,
`FirewallRuleCollection`, `FirewallRule`, `PrivateEndpoint`, `PrivateDnsZone`,
`NetworkGateway` (VPN, ExpressRoute, NAT), and `LoadBalancingResource`
(Application Gateway, Load Balancer). `SharedService` is derived, not ingested.

Sub-resources are **first-class entities** with their own derived IDs, not
nested blobs, so a single NSG rule can be cited as evidence, traversed in the
graph, and scoped independently.

ARG queries are **split per resource family** (10 specs). A throttle on one
family degrades that family only; it does not blank the whole topology.

## The four questions

| Question | Route |
| --- | --- |
| What depends on the hub? | `/api/v1/network/topology/hubs/{vnet_id}/dependents` |
| Which spokes bypass the firewall? | `/api/v1/network/firewall-bypass` |
| Can UAT reach PROD, and which rules decide? | `/api/v1/network/traffic-flow` |
| Which rules are too broad? | `/api/v1/network/rule-findings` |
| Which gaps violate the approved design? | `/api/v1/network/gaps` |

## Three safety properties

### 1. Tri-state matching — `indeterminate` is a real verdict

`AddressSpec.contains_address` and `overlaps` return `None`, not `False`, when
a match cannot be decided (an unresolvable service tag, an unobserved
endpoint). `_verdict` checks `unknowns` **before** it concludes deny.

A flow therefore resolves to `allowed`, `denied`, or `indeterminate`, and the
last means *no claim is made in either direction*. The UI renders it as a
warning and states explicitly that it is not an allow. Collapsing it into
either bucket would convert a refusal to guess into a false assurance.

### 2. Hub classification is evidence-scored, not name-based

`HUB_SIGNAL_WEIGHTS` scores observable facts — hosts a firewall, hosts a
gateway, allows gateway transit, has many peerings — against a threshold of
3.0. A hub-sounding name contributes only 0.5, so naming convention alone can
never classify a VNet as a hub. Every classification carries its `signals`.

### 3. An absent design policy is a reportable state

With no declared design, only **structural** gaps can be found (one-way
peering, missing UDR, firewall bypass), never **conformance** gaps (an
unapproved peering, a missing required control). `/gaps` returns
`intended_design_declared: false` and the UI surfaces a banner, rather than
letting an empty conformance result read as compliance.

## Scoping

Scope filters the **snapshot**, not just the classifications. Counts,
connection IDs, and derived summaries are narrowed along with the resources, so
a caller scoped to one subscription cannot infer the size of the estate beyond
their grant.

One deliberate exception: a peering **link** whose remote VNet is out of scope
stays visible. Hiding it would conceal a real dependency the scoped owner is
accountable for. The remote's own resources remain withheld.

Peers referenced but never ingested are reported in
`unresolved_peer_vnet_ids` — a known unknown (that subscription is not
onboarded), not an absence.

## Tightening analysis

Detects overly broad rules, unused rules, shadowed rules, Internet inbound,
cross-environment access, DEV-to-PROD reachability, SQL/SSH/RDP exposure, wide
source CIDRs, any-any rules, and missing owners.

"Unused" is inferred **structurally** — no NIC or subnet was observed that the
rule could apply to. It does not mean no traffic matched it. Findings are
therefore `medium` confidence in the evidence envelope.

Azure's implicit default NSG rules are synthesized when not present in the
ingested data, and marked as synthesized, because evaluating a rule set without
them produces the wrong verdict at the tail of the priority order.

## Design policy

Optional YAML declaring the approved topology: hub VNets, approved peerings (by
name, bidirectional or not), required controls, and environment isolation
rules. Loaded via `build_service(rows, policy_path=...)`.

### Custom rules (declarative DSL)

The ten built-in checks are hand-written Python. Site-specific intent — "prod
subnets must carry an owner tag", "no VNet outside these regions" — is knowable
only to the customer, and there will always be more of it than we can
anticipate. Those rules are authored declaratively in the policy document and
evaluated at runtime by `network.rule_engine`, with no code change or redeploy.

A rule has two clauses. `where` selects the resources in scope (omit it to
select all of the target); `assert` states what must hold for each selected
resource. A selected resource failing any assertion yields one gap.

```yaml
rules:
  - rule_id: prod-subnets-need-owner
    name: Production subnets must declare an owner
    severity: medium
    parameters:
      target: subnets
      where:
        - field: environment
          equals: prod
      assert:
        - field: tags.owner
          exists: true
```

**Targets** — `vnets`, `subnets`, `nsgs`, `nsg_rules`, `nics`, `route_tables`,
`routes`, `peerings`, `firewalls`, `private_endpoints`, `private_dns_zones`,
`gateways`, `load_balancers`, `private_link_resources`.

**Operators** — one per condition:

| Operator | Meaning |
| --- | --- |
| `equals` / `not_equals` | Case-insensitive string comparison |
| `in` / `not_in` | Membership in a list |
| `contains` / `not_contains` | Substring, applied across list-valued fields |
| `matches` / `not_matches` | Glob pattern (`fnmatch`), e.g. `10.*` |
| `exists` | Field is present and not empty (`true`/`false`) |
| `gt` / `gte` / `lt` / `lte` | Numeric comparison |
| `in_cidr` / `not_in_cidr` | Address or prefix falls inside a CIDR |

`field` is a dotted path resolved across dataclass attributes, properties, and
dict keys alike, so `tags.owner` and `allows_public_access` both work without
the author knowing which is which.

The rule that motivated this engine is expressible directly:

```yaml
  - rule_id: private-endpoints-preferred
    name: Private endpoints should be used when possible
    severity: high
    parameters:
      target: private_link_resources
      assert:
        - field: allows_public_access
          equals: false
```

which yields, per offending resource:

```
sa1 does not satisfy: allows_public_access equals False (observed: true)
```

**Three guarantees, in priority order:**

1. **No code execution.** There is no expression evaluator, no `eval`, and no
   callable injection. A policy document is untrusted input — it arrives over
   the API from whoever can edit policy — so the worst a malformed rule can do
   is fail to match.
2. **Silence is never a pass.** A rule naming an unknown target or an
   unsupported operator does *not* quietly evaluate to compliant. It is
   reported through `invalid_rules`, so the UI can distinguish "checked and
   clean" from "never ran". `POST /network/policy/preview` returns the same
   list as a warning, so an author sees a broken rule before saving it.
3. **Evidence over verdicts.** Every gap records the assertion that failed and
   the value actually observed, so a reviewer can audit the finding without
   re-running the engine.

The language is deliberately not Turing-complete. It expresses "which
resources" and "what must be true of them". Anything needing traversal or
correlation belongs in a hand-written check, or in the ontology traversal
queries below, where it can be reasoned about and tested directly.

## Network reachability queries

`OntologyQueryService` answers two traversal questions over the ontology graph.
Reachability is deliberately distinct from the structural `impacted` walk: two
applications can depend on each other while being network-isolated, so treating
`depends_on` as a network path would manufacture false exposure findings.

| Question | Answers |
| --- | --- |
| `network reachable` / `network blast radius` | Everything a packet could reach from the named entity |
| `network exposure` / `internet reachable` | Which network boundaries the entity reaches, and in which direction |

Both record the **path** taken as a list of predicate names, so a finding is
evidence a reviewer can refute rather than a bare assertion.

Exposure results carry a `direction`. The ontology collapses six distinct Azure
gateway types into one `NetworkGateway` entity, but they do not all mean the
same thing: a NAT gateway is an egress path, not an open door. Direction is
recovered from the ARM resource type — `inbound`, `outbound`, or `unknown` when
it cannot be determined. An unclassifiable boundary is reported as `unknown`
rather than dropped, because missing data must not become an implicit "safe"
verdict.

Absence of a path yields no finding. That is the absence of evidence, never
evidence of compliance.

## Evidence

Every response carries the standard envelope. Network evidence names
`network.NetworkIntelligenceService` as the source engine and stamps the
snapshot's observation time, so freshness is banded honestly — an unstamped
snapshot reports `unknown`, never `fresh`.
