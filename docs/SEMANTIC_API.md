# Semantic Knowledge Layer API

## Python API

The semantic API is graph-first. It resolves durable semantic relationships and
does not imply that mutable source values are current. Hybrid APIs explicitly
request live observations and return separate graph and source freshness.

Create an engine from a governed Fabric runtime:

```python
runtime = build_runtime(FabricRuntimeConfig.load("fabric.config.yaml"))
semantic = runtime.semantic_engine()
```

Agent-facing methods:

```python
semantic.get_application_context("Payments")
semantic.get_service_context("Retail")
semantic.get_resource_context("vm-payments")
semantic.get_risk_context("vm-payments")
semantic.get_impact_context("vm-identity")
semantic.search_operational_context("Find all production applications")
```

Canonical agent API aliases are also available without the `get_` prefix:

```python
semantic.application_context("Payments")
semantic.service_context("Retail", subject_type="BusinessService")
semantic.resource_context("vm-payments", subject_type="VirtualMachine")
semantic.subscription_context("sub-1")
semantic.risk_context("vm-payments", subject_type="VirtualMachine")
semantic.impact_context("vm-identity", subject_type="VirtualMachine")
semantic.search("Find all production applications")
```

Additional reusable view:

```python
semantic.get_subscription_context("sub-1")
```

Natural-language routing:

```python
semantic.query("What owns this VM?", subject="vm-payments")
semantic.query("What is the blast radius of this failure?", subject="vm-identity")
semantic.query("Show upstream dependencies", subject="Payments")
semantic.query("Show downstream impact", subject="Identity")
semantic.query("Show operational risk", subject="vm-payments")
semantic.search_operational_context(
    "Find critical infrastructure by business service Retail"
)
```

## Hermes tool

The Semantic API remains available to trusted Python and operator CLI callers. Agents receive only `operations_analysis`, which consumes these APIs internally and adds bounded explainable reasoning and advisory recommendations.

Input:

```json
{
  "question": "What applications are impacted by this outage?",
  "subject": "vm-identity",
  "subject_type": "VirtualMachine"
}
```

`subject` should be the exact semantic name. `subject_type` is optional and resolves cross-domain name collisions for impact queries. Without it, impact lookup is restricted to impact-capable domains and fails closed if still ambiguous.

## CLI

```bash
uv run hermes-arg semantic \
  "Show application context" \
  --subject Payments \
  --config fabric.config.yaml

uv run hermes-arg semantic \
  "What services are at operational risk?" \
  --config fabric.config.yaml
```

## Context response contract

```json
{
  "context_type": "resource",
  "subject": {
    "entity_type": "VirtualMachine",
    "name": "vm-payments",
    "lifecycle_status": "active"
  },
  "sections": {
    "applications": [],
    "ownership": [],
    "compliance": {},
    "patching": {},
    "advisor_findings": [],
    "security_findings": [],
    "resource_health": {},
    "lifecycle": {}
  },
  "risk": {
    "score": 75,
    "level": "Critical",
    "factors": {}
  },
  "graph_version": "semantic-08872d02644f1f55",
  "graph_freshness": "2026-08-17T00:00:00Z",
  "live_observed_at": null,
  "source_status": {}
}
```

Graph-only responses have `live_observed_at: null`. Hybrid responses populate
`live_observed_at` and `source_status` for each queried provider. Responses
never include raw payloads, tenant/subscription IDs, lineage, semantic
metadata, or ingestion IDs.

The legacy snapshot-backed provider is compatibility-only for unscoped/demo
reads. Scoped workbench reads use the hybrid path: durable graph context plus
request-time authoritative observations, with separate graph and live freshness
metadata. Current live sources are:

- Azure Resource Graph `Resources` for resource, search, business-service, and
  network topology state.
- Azure Resource Graph `patchassessmentresources` and
  `patchinstallationresources` for vulnerability exposure and patch remediation
  planning.
- Azure Resource Graph `alertsmanagementresources` for active incident/alert
  queues.

Where an authoritative live source is not configured, the API returns an
explicit `source_status`/warning instead of treating a stale snapshot as current.

Unknown risk is represented explicitly with `score=null`, `level="Unknown"`, and an empty factor map. It is never converted to zero or Low.

List/search responses return at most 50 items by default, include the total `count`, and set `truncated=true` when more results exist. Impact responses provide `collection_metadata` for each impacted collection and enforce one tree-wide traversal budget. Context responses provide `section_metadata` with `count`, `returned`, and `truncated` for every list section. They return a fixed intent label rather than echoing the caller's question. Knowledge versions are opaque `semantic-*` fingerprints, never ingestion run IDs.

## Errors

- Unknown subject: `LookupError`
- Ambiguous exact name: `ValueError`
- Unsupported query/search: `ValueError` with supported intents
- Invalid/dangling Ontology snapshot: `ValueError`; no engine is served
- Missing Fabric persistence: runtime error until the first successful synchronization

The Hermes tool boundary maps these exceptions to fixed, non-reflective error messages so caller-supplied resource identifiers are never echoed. Detailed exceptions remain available only to direct operator/Python callers.
