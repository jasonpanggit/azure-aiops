# Semantic Knowledge Layer runbook

## Purpose

Operate the read-only Semantic Layer above Fabric Ontology. Do not manually patch cache/index state; correct Azure/Fabric facts and resynchronize.

## Readiness checks

1. Confirm the latest Fabric ingestion state is `completed`.
2. Confirm Ontology health has zero synchronization errors.
3. Run semantic smoke queries:

```bash
uv run aiops-inventory semantic "Find orphan resources" --config fabric.config.yaml
uv run aiops-inventory semantic "Find ownership gaps" --config fabric.config.yaml
uv run aiops-inventory semantic "What services are at operational risk?" --config fabric.config.yaml
```

4. Run a known entity context and verify `freshness` and `knowledge_version`.

## Impact-analysis examples

### VM failure

```bash
uv run aiops-inventory semantic \
  "What is the blast radius of this failure?" \
  --subject vm-identity \
  --config fabric.config.yaml
```

Traversal:

```text
VM
└── member_of → Application
    ├── incoming depends_on → downstream Applications
    ├── incoming contains → Business Services
    └── implements → Services
```

Shared owners, support teams, environments, or services are not used as bidirectional bridges.

### Patch failure

```text
Patch Assessment
└── evaluates → Server
    └── member_of → Application
        └── contained by → Business Service
```

### Subscription outage

```text
Subscription
└── scoped resources
    └── Applications
        ├── downstream dependencies
        └── Business Services
```

## Telemetry

Monitor:

- `semantic.query.latency`
- `semantic.graph.traversal.latency`
- `semantic.context.generation.latency`
- `semantic.cache.requests{result=hit|miss}`
- `semantic.cache.hit_ratio`
- `semantic.knowledge.freshness` measures age of the source-derived watermark.
- `semantic.ontology.synchronization.lag` measures age of the completed Ontology synchronization.

The in-process cache also exposes exact hit/miss counts and `hit_ratio` through `SemanticCache.stats()`.

Alert on:

- sustained query or traversal latency regression;
- freshness/ontology lag beyond the ingestion SLO;
- cache hit ratio collapse after warm-up;
- semantic snapshot validation failure;
- sudden risk, ownership-gap, or orphan growth.

## Cache operations

- Default cache is TTL and LRU bounded.
- Every read includes `knowledge_version`; a new Ontology synchronization invalidates stale entries automatically.
- Restarting the process safely starts with an empty cache.
- Use `semantic.cache.clear()` only for diagnostics; it does not change authoritative knowledge.

## Runtime bounds

```yaml
fabric:
  semantic:
    max_results: 50
    max_traversal_nodes: 500
    max_traversal_depth: 32
    max_source_rows: 50000
    max_serialized_bytes: 1000000
```

`max_traversal_depth` must be between 1 and 256 to keep impact-tree construction below Python recursion limits.

All values are exact positive integers and the serialized ceiling must be at least 1024 bytes. Exceeding source, traversal, result, or byte bounds fails closed rather than bypassing the Semantic Layer.

## Failure response

1. If subject lookup fails, verify exact semantic name and active lifecycle state.
2. If snapshot validation fails, inspect Ontology health and dangling relationship reports; do not bypass validation.
3. If freshness is stale, inspect ARG/Fabric ingestion state and run `Sync operational ontology`.
4. If a risk score looks wrong, inspect returned factor points and correct ownership, patch, Advisor, security, criticality, or environment facts at their authoritative source.
5. If impact is incomplete, verify the deterministic `member_of`, `depends_on`, `contains`, `implements`, or `evaluates` relationship—not the cache.

## Security

- Agents receive semantic projections only.
- Direct Delta and raw Azure query tools are not registered for agent use.
- Fabric and OneLake permissions still govern the service identity that assembles snapshots.
- Semantic responses must continue to pass `SemanticValidator` before release.
- Probe literal, percent/Base64/Base32/hex/Unicode-escaped ARM and GUID values in both mapping keys and values; public responses must redact them.

## Verification

```bash
uv run --extra test pytest
uvx ruff check . --exclude .venv --exclude live-data --exclude mock-fabric-lakehouse
uvx bandit -r src -q
```

Sample scenario: `tests/fixtures/sample_semantic_scenarios.json`.
