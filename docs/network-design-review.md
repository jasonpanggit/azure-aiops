# Network design review v1 (source/offline qualification)

This implements adoption Waves 0–1 only. On Network, open Operations Copilot and
select **Review network design**. The existing `network` specialist invokes
`firewall_nsg_gaps` with `category: design_review`. Its existing authorization,
scope filtering, inventory/topology provider and orchestration budgets still
apply. No tools, specialists, grants, provider configuration, deployment,
catalog/CI automation, or mutation authority are added.

The versioned scenario declaration is `src/operations/network_scenarios.py`,
alongside the locked specialist contract. The locked manifest is unchanged.
The deterministic evaluator is `src/network/scenarios.py`; it consumes the
already acquired, server-scoped `NetworkIntelligenceService` snapshot.

Bounded changed paths (16; no commits or deployment):

- `src/network/loader.py`, `models.py`, `scenarios.py`, `tightening.py`
- `src/onboarding/network_normalize.py`
- `src/operations/maf_orchestrator.py`, `network_scenarios.py`, `orchestration_service.py`, `tools.py`
- `web/src/components/ui/CopilotDrawer.tsx`, `CopilotDrawer.test.tsx`
- `web/src/lib/copilot/page-adapters.ts`, `page-adapters.test.ts`
- `tests/test_network_design_scenarios.py`
- `README.md`, `docs/network-design-review.md`

## Baseline and evidence availability

Baseline source: `9d385ae0857db6acd2f28f850e7ca6183a82ea9c`.

| Surface | Baseline source evidence | Slice qualification |
|---|---|---|
| Specialist and governed tool | Network already owns `firewall_nsg_gaps` on Network; `category` is a reviewed argument | Reused without widening grants; manifest/schema parity tested |
| Acquisition and scope | Existing governed network provider, inventory normalization and `service.scoped()` | Reused, no parallel collector; provider read access and deployed execution remain live-unqualified |
| Public/private access | Resource-level endpoint-gap detectors and retained service settings existed | Explicit private-access policy added; nested retained public-network settings projected; absent/unsupported settings remain unknown |
| Endpoint approval and DNS | Endpoint state, zone IDs, subnet and VNet links already modeled | Observed approval and available binding checks; absent dependencies remain unknown, no resolution claim |
| Peering | Observed state, both-side topology and addresses existed | Address overlap and complementary gateway-transit checks added; missing reverse coverage is unknown, not a fabricated broken remote peer |
| NSGs | Existing tightening/shadow analysis | Explicit categories/directions and expiring exceptions added; source-port-aware shadow checks repaired |
| Normalization defaults | Missing gateway flags and NSG fields could become defaults | New observation-presence stamps prevent defaults becoming review evidence; legacy property-bearing rows without stamps remain unknown until refreshed |
| Copilot | Scoped drawer, canonical endpoint, citations and deterministic fallback existed | Added bounded starter, scenario context and deterministic anchor; actual selected-scope abort and late-result rejection tested |
| Completeness/freshness | Snapshot timestamp exists; no qualified acquisition-completeness receipt on this read contract | Acquisition completeness is explicitly unknown, never inferred from an empty collection or the visible page denominator |

The original six executable acceptance cases in
`tests/test_network_design_scenarios.py` failed before implementation:
`category: design_review` returned `empty`/no data and no cited synthesis.
The sanitized full fixture expects exactly:

| Scenario | Expected finding | Expected non-finding/unknown |
|---|---|---|
| Private access | `public_access_enabled` for the storage resource even with an approved endpoint | DNS binding missing is unknown; no assertion that an endpoint disables public access |
| Peering integrity | `address_overlap` once per pair | Complementary hub `allow_gateway_transit=true` / spoke `use_remote_gateways=true` is valid, not an asymmetric-flags finding |
| Reviewed NSG exposure | `internet_inbound` for the observed SSH rule | Fully shadowed rules and other directions are excluded; configured risk is not proven reachability |

The expanded corpus covers missing/invalid/disabled policy, missing settings,
legacy defaults, stale timestamps, scoped-out peers, active/expired exceptions,
bounded results, canonical API fallback, narrator contract rejection and citations.
The UI corpus exercises the actual scope selector and Cancel request while a
response is pending, including a transport that ignores abort.

## Explicit policy opt-in

Use the existing reviewed network design policy mechanism. This documentation
does not authorize applying or changing any runtime policy. Example rule entries
for an independently reviewed policy:

```yaml
rules:
  - rule_id: design-review-private-access
    name: Private access required for reviewed storage resources
    enabled: true
    parameters:
      resource_types: [microsoft.storage/storageaccounts]
      exceptions: []
  - rule_id: design-review-peering-integrity
    name: Reviewed peering configuration integrity
    enabled: true
    parameters:
      require_gateway_transit: false
      exceptions: []
  - rule_id: design-review-nsg-exposure
    name: Reviewed inbound internet exposure restrictions
    enabled: true
    parameters:
      categories: [internet_inbound]
      directions: [Inbound]
      exceptions: []
```

These rules run only in the explicit design-review invocation. The ordinary
policy/gaps page may list them as unevaluated by its legacy gap analyzer; that
is not proof the on-demand review has run. Missing/disabled scenario rules
produce unknown/not-evaluated assessments, not shipped best-practice violations.
Disable the scenario rules to stop their evaluation without changing grants.

`resource_types` must be an explicit nonempty list. Only explicitly observed
Enabled/Disabled public-access values are interpreted; unsupported values and
Fabric tenant/workspace semantics are unknown. Gateway transit is optional
unless explicitly required; requiring it also needs reviewed `hub_vnet_names`.
Allowed NSG categories are `internet_inbound`, `any_any`, `wide_source_cidr`,
`broad_port_range` and `sensitive_port_exposure`. Directions are explicit.
Partial shadowing is not proof an entire rule is suppressed.

An exception requires an exact resource ID (an NSG **rule** ID for NSG findings),
`reference`, and timezone-qualified `expires_at`. Active exceptions retain the
underlying assessment and reference as `excepted`; expired exceptions retain
the reference without suppressing findings. Invalid exception policy is unknown.
No exemption or approval is inferred from tags or created by the model.

## Output and limits

Existing `gaps` carries policy findings. `design_review` carries scenario version,
policy SHA-256, observation/evaluation window, snapshot freshness, exact evaluated
counts, assessments, exception references and resolvable internal evidence
sources. The tool envelope supplies the externally cited `tool:<call>:<index>`
evidence. Lists remain capped at 25 with explicit truncation warnings; counts
describe evaluated observations, not an authorized-estate denominator.

`observed` means a configuration fact was observed, **not compliant/healthy**.
Unknown acquisition coverage is independent of visible-page coverage.
The available snapshot timestamp is not a per-resource freshness attestation.
No flow telemetry, effective routes, DNS query results or end-to-end access
test is implied by this review.

The coordinator receives bounded assessments and applicable policy context.
Its output cannot replace the deterministic anchor; invalid citation/schema
responses and unavailable Foundry retain cited deterministic evidence with
explicit degraded provenance. Client cancellation aborts the canonical request
and invalidates its response generation; it does not promise rollback of
already completed server reads.

## Offline receipt and live gates

On the sanitized fixture, after warm-up, 100 in-process calls measured:

| Path | Median | p95 | Findings | Model requests/tokens | Governed calls |
|---|---:|---:|---|---|---:|
| Original unimplemented-category equivalent | 0.004 ms | 0.005 ms | None (3 expected findings missed) | 0 / 0 | 1 |
| Implemented review | 0.157 ms | 0.166 ms | Exactly the 3 expected checks; 0 unexpected | 0 / 0 | 1 |

The original timing uses the unchanged legacy category-filter branch with an
unimplemented category; original behavior was also reproduced by the failing
pre-implementation fixtures. It is not a provider/network latency benchmark.
All fixture policy references resolve, one DNS unknown remains, and the
canonical API test observes one provider resolution. Stub narration tests prove
contract handling, not model quality or real token consumption.

Focused offline verification: 744 Python tests, 246 web tests, changed-path Ruff,
web ESLint and TypeScript `--noEmit` passed. Python reports existing
FastAPI/Starlette deprecation warnings. No live acceptance was attempted.
The frozen downstream topology byte-contract gate also passes; observation
stamps remain internal and do not change the existing REST resource shapes.

An operator must independently qualify deployed identity, scoped provider read
access, provider pagination/completeness, freshness, immutable tool/runtime
parity, real Foundry narration quality/latency/tokens and nonproduction UI
acceptance. Foundry publication/identity and native ontology lifecycle gates
remain independent. Unified Deployment retains merge/deployment ownership.
