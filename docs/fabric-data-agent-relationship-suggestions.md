# Fabric Data Agent ontology review

The Fabric Data Agent is a read-only, advisory reviewer over curated Gold and
ontology products. It does not own resource identity, ontology vocabulary,
proposal approval, relationship admission, generation publication, or active
pointer mutation.

## Authority model

| Responsibility | Authority |
| --- | --- |
| Resource identity, ownership, and lifecycle | Unified inventory read port |
| Entity and relationship derivation | Deterministic ontology pipeline |
| Quality, vocabulary, endpoint, scope, and generation validation | Deterministic validators and Phase 13 proposal policy |
| Relationship suggestions and explanations | Fabric Data Agent or the configured proposal-only curator |
| Review decisions | Phase 13 append-only review store with authenticated RBAC identity |
| Publication and rollback | Dedicated Phase 13 publisher identity |

Data Agent confidence is ranking metadata only. It can order a review queue,
but it can never authorize an ontology edge.

## Supported review scenarios

The governed Data Agent definition selects curated Gold products plus:

- `ontology_entities`
- `ontology_relationships`
- `ontology_health`
- `ontology_quality_report`
- `metadata_publication_manifest`
- `metadata_source_status`

These sources support bounded review questions such as:

- Which active entities have no relationships?
- Which deterministic quality checks failed?
- Are relationship endpoints active and present?
- Which predicates or entity-type combinations fall outside the vocabulary?
- Which links are stale, retired, missing lineage, or temporally inconsistent?
- What is the provenance and confidence distribution of the current graph?
- Which ontology projections are active, empty, stale, or retired?

The deterministic code computes verdicts. The Data Agent only explains,
prioritizes, or proposes follow-up investigation.

## Durable proposal workflow

Phase 13 already provides the asynchronous management path. Do not build a
second Data-Agent-owned workflow:

1. The coordinator captures one immutable source generation.
2. Deterministic review signals are attached to every bounded evidence batch.
3. A proposal-only curator may return relationship proposals with citations.
4. `OntologyRunStore` persists proposals immutably.
5. An authenticated `approver` or `admin` records an append-only review event
   containing the real RBAC role, policy version, approval timestamp, proposer
   identity, reason, and computed separation-of-duty result.
6. `ProposalPolicy` checks vocabulary, endpoints, endpoint lifecycle, scope,
   evidence freshness, evidence generation, corroboration, review state, and
   pair-release gates.
7. Production remains hard-shadow: model-derived relationships are not
   admitted into the authoritative candidate.
8. Only the dedicated publisher can publish a fully validated deterministic
   generation.

The legacy `relationship_suggestions.status` field is retained for storage
compatibility but is not an approval signal. `ontology_pipeline.run()` has no
suggestion input and no model-derived merge path.

## Gold-grounding response contract

Each successful response is line-delimited JSON. Every finding contains:

- `finding_id`
- the pinned `generation_id`
- one or more citations
- `scope_ok: true`
- a bounded factual `summary`

Each citation contains its own full ARM `resource_id`, `generation_id`,
`gold_table`, `row_key`, `as_of`, and `confidence`. Citation/resource
associations are never inferred by list position. Model-authored summaries are
not forwarded to Operations Copilot; narration receives only validated
citations plus a deterministic count summary.

The application classifies every request as one of:

- `success`
- `healthy_empty`
- `malformed`
- `denied`
- `timeout`
- `stale`
- `unavailable`

There is one cancellable async transport attempt within the request budget.
The JSON-RPC version and request ID must match. Invalid or out-of-scope
evidence is withheld from narration; only sanitized conflict reasons are
retained. Inventory remains authoritative when Gold and inventory disagree.
Healthy-empty is accepted only when a caller-supplied authoritative generation
manifest exactly matches the agent's structured proof.

## Deployment

The relationship-agent deployment requires an explicit immutable generation:

```bash
.venv/bin/python scripts/deploy-relationship-suggestion-agent.py \
  --generation-path "<immutable-generation-path>" \
  --source-generation "<source-generation-id>"
```

The Gold-grounding agent uses the same required arguments:

```bash
.venv/bin/python scripts/configure-gold-grounding-agent.py \
  --generation-path "<immutable-generation-path>" \
  --source-generation "<source-generation-id>"
```

Add `--publish` only during a separately authorized Fabric mutation window.
Do not rerun publication merely to validate this code.

The Data Agent management and runtime planes are separate:

- Items REST API: create, update definition, publish
- MCP `tools/call`: query the published agent

A successful publish does not prove runtime readiness. The capabilities API
therefore reports configured credentials as `configured_unverified`, not
`available`, until a separate runtime verification signal exists.

## Latency and execution model

Historical live requests took about 64 seconds, exceeding the application's
30-second turn budget. The synchronous Gold path remains fail-closed and
bounded. Ontology review runs through the durable asynchronous Phase 13
workflow; deterministic review signals travel as generation-bound batch
metadata, and user turns should read previously validated proposals and review
signals rather than wait for a Data Agent call.

The environment token fallback is configuration, not proof of per-user OBO.
Runtime enablement must require a caller-bound delegated token and retain
application-side scope checks unless Fabric row-level security independently
enforces the same effective scope.

Refresh current latency, identity, capacity, selected-table, and MCP evidence
before enabling any runtime path. Do not assume historical measurements remain
current.

## Prohibited patterns

- Writing directly from a Data Agent to authoritative ontology tables
- Auto-promoting an edge from model confidence
- Treating a mutable table status as approval
- Publishing a proposal that bypasses Phase 13 policy and validator checks
- Allowing workspace-wide queries when effective scope cannot be enforced
- Treating stale, malformed, denied, or unavailable evidence as healthy-empty
- Letting Data Agent evidence override inventory identity or lifecycle
- Retrying a slow Data Agent call beyond the declared wall-clock budget
