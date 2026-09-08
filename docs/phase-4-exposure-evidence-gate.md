# Phase 4 Exposure evidence gate

Phase 4 may start only when the live supported container path is exact,
generation-bound, complete, and reproducible. This gate is intentionally
stricter than “a container finding exists” or “a deployment probably uses this
repository.”

## Required traversal

For one live authorized scope and one retained readable generation, the
evidence must round-trip through:

1. Defender vulnerability observation;
2. canonical immutable `sha256` digest;
3. granular Fabric observation and digest entities;
4. supported Container Insights deployment observation at the exact digest and
   observation time;
5. typed ontology deployment relationship;
6. observed workload;
7. workload/application/service context when those relationships are actually
   supported.

The reverse traversal must return the same observation, digest, deployment,
and workload identities. The evidence report records hashes and aggregate
counts, not raw identifiers.

## Completeness contract

The gate report must include:

- represented workload count;
- total observed workload count;
- unknown workload count;
- excluded count and bounded reason codes;
- source-family status and freshness;
- generation and configuration binding;
- release commit/image binding.

Passing requires `represented > 0`, `total >= represented`, a successful exact
round trip, and no unclassified exclusion. A partial result remains useful
operational evidence but is not Phase 4 readiness.

## Evidence that cannot pass

The following remain explicit `typed_unknown` or blocked:

- repository or registry-name correlation without digest;
- mutable image tags;
- Azure Resource Graph-only deployment inference;
- source-code or build-pipeline repository references;
- workload ownership inferred from naming or labels;
- stale observations outside the accepted event-time relationship;
- carried-forward source evidence that was never previously exact;
- conflicting digests;
- unavailable Container Insights workspace;
- incomplete pagination or source checkpoint;
- synthetic benchmark data presented as live workload evidence.

No score, UI label, operator assertion, or model inference may upgrade these
states to exact.

## Executable gate

The release validator must report all of the following as pass:

- `defender_exact_digest`;
- `supported_container_insights`;
- `fabric_sql`;
- `persistence_ontology_round_trip`;
- `api_web_scope_identity`;
- `qualified_100k_benchmark`;
- `phase4_exact_path`.

The canonical blocking reason is:

```text
exact_supported_defender_digest_to_container_insights_workload_round_trip
```

Any missing prerequisite keeps the rollout lanes fail-closed and Phase 4
blocked. Downstream symptoms such as absent Gold tables, an unqualified
benchmark, or no ontology round trip are recorded under this one residual gate
when they share the same unavailable exact-source publication chain.

## Operational proof

The retained artifact must be:

- JSON;
- sanitized;
- non-zero/blocked on missing evidence;
- bound to immutable release/configuration/generation metadata;
- free of credentials, cursor key values, raw provider payloads, and scoped
  identifiers;
- accompanied by the focused backend/UI/Terraform suite results;
- accompanied by alert routing, cursor rotation, API/web identity, exact
  action allowlist, and zero container-operation evidence.

The authoritative artifact for Plan 03.1-19 is:

```text
.planning/phases/03.1-exposure-reliability-and-scale/03.1-19-LIVE-EVIDENCE.json
```

## Current disposition

The current artifact is blocked. Live source refresh, the 435-table Fabric
publication, Fabric SQL connectivity, ontology validation, Gold schema
publication, and all automated suites pass. The live exact source chain is
empty for the authorized dev scope: the qualified query sees zero server and
container-image Gold facts, zero active digest-to-deployment edges, and zero
deployment-to-application edges. No exact Defender
digest-to-supported-workload round trip exists. Phase 4 remains blocked;
repository, tag, unknown, or incomplete evidence must not be substituted.

## Unblocking sequence

1. Add or observe exact supported Defender digest and Container Insights
   deployment/workload evidence in the authorized dev scope.
2. Re-run the deployed managed-identity source sync.
3. Publish and reconcile a non-empty retained Gold generation.
4. Prove detailed Defender subassessments remain in Silver while ontology
   contains only canonical current digest-CVE exposures with evidence
   references; duplicate source events must not create duplicate graph nodes.
5. Run the derived-scope 100k Fabric SQL benchmark.
6. Run the live validator and exact forward/reverse traversal.
7. Require represented/total completeness and a single generation.
8. Only then advance write shadow, reader canary, web canary, and governed
   handoff canary.
