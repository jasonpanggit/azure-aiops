---
status: diagnosed
trigger: "Troubleshoot the root cause of failed Exposure publication execution aiops-dev-exposure-publication-ox0p2j1 without modifying source or cloud state."
created: 2026-09-13T14:27:12+08:00
updated: 2026-09-13T15:52:30+08:00
---

## Current Focus

hypothesis: Confirmed: canonical Exposure emits three relationships per current digest-CVE observation, but commit `4199bb61bd` lowered the granular and shared relationship bounds to 250000; the retained 87240-observation generation deterministically requires 262786 granular and 263634 merged relationships.
test: Complete — exact retained source replay reproduced the mapper exception, raised-cap differential isolated the threshold, exact merges and raised-cap validation passed, and deployed image ancestry was verified.
expecting: Observed — default build fails at 250000; changing only the in-memory relationship limit yields a valid 263634-relationship merged graph.
next_action: Hand off a coordinated capacity remediation and regression tests; do not rerun publication until all producer, synchronizer, and reader limits are aligned.
bug_class: bohrbug
candidate_causes:
  - code: commit `4199bb61bd` lowered granular relationship capacity from 1000000 to the 250000 default while retaining three edges per canonical observation
  - data: valid retained generation contains 87240 canonical digest-CVE observations, whose required three-edge fan-out alone is 261720
  - config: deployed semantic max_relationship_rows is also 250000 and FabricSyncService does not thread a larger publication limit
  - environment: disproved as immediate cause because the 16Gi execution had no restart/OOM and the same retained input fails locally with ValueError
and_gate: yes — the failure requires both the regressed 250000 code/config bound and valid production cardinality above 83333 canonical observations
reasoning_checkpoint:
  hypothesis: "Commit 4199bb61bd causes deterministic activation failure because each canonical VulnerabilityObservation emits three required relationships, so 87240 observations exceed the reverted 250000 relationship cap."
  confirming_evidence:
    - "Exact retained replay raises `ValueError: Ontology relationship bound exceeded` inside GranularExposureOntologyMapper.build_rows."
    - "Raised-cap replay produces 262786 granular and 263634 merged relationships; both exact merges and validation pass."
    - "Deployed image tag main-01a9aaf2e descends from 4199bb61bd and contains the 250000 default plus the three relationship rules."
  falsification_test: "The hypothesis would be false if the exact retained generation built under the default cap, failed before RelationshipBuilder, or failed merge/validation after only raising the cap; none occurred."
  fix_rationale: "Aligning one publication/semantic relationship capacity of at least 263634 (the prior 1000000 bound provides tested headroom) preserves the accepted v2 edge contract and removes the actual guard failure; deleting an edge would alter ontology semantics."
  blind_spots: "No publication was started and no cloud state was mutated; predecessor lifecycle rows and post-publication semantic startup were not executed end-to-end, so the fix must retain a full replay/canary gate and memory observation."
  candidate_causes:
    - "code: relationship-cap regression in 4199bb61bd"
    - "data: valid 87240-row canonical exposure cardinality triggers the regression"
    - "config: deployed semantic reader retains the same insufficient 250000 cap"
  and_gate: "yes — undersized bound AND valid production cardinality are jointly required"
reasoning_checkpoint:
tdd_checkpoint:

## Symptoms

expected: The D4/16Gi publication completes Fabric table writes, writes one `metadata_patch_snapshot` barrier per authorized subscription, stages Gold, and activates the readable generation pointer.
actual: Temporal projection completed after 4058.090 seconds with 174498 entities and zero failures; container projection completed after 6.109 seconds with 87241 entities and zero failures; activation then failed before ontology construction or table publication began.
errors: The only emitted terminal error is safe code `ACTIVATION_FAILED`; the CLI deliberately suppresses the chained exception. Execution status is Failed with zero restarts. Peak memory was approximately 6.88GiB and peak CPU approximately 1.28 cores, ruling out D4 memory exhaustion.
timeline: Execution `aiops-dev-exposure-publication-ox0p2j1` ran from 2026-09-13T05:01:28Z until failure at 2026-09-13T06:22:45Z using image digest sha256:810389601f5fc7a83588e3e8a2887ab072f1cf9525cd26012b34789c7dec6090.
reproduction: Run `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` against the live retained data. Do not rerun operationally until the deterministic defect is diagnosed.

## Evidence

- timestamp: 2026-09-13T14:27:12+08:00
  checked: structured activation logs
  found: temporal projection completed with 174498 entities; container projection completed with 87241 entities; no ontology_construction start or table_publication event followed
  implication: failure occurred in the code between container completion and ontology construction start, specifically granular ontology build/merge and temporal cleanup

- timestamp: 2026-09-13T14:27:12+08:00
  checked: Azure Monitor metrics and Container Apps execution state
  found: peak memory 7385415680 bytes, peak CPU 1276404896 nanocores, zero restarts, terminal status Failed
  implication: failure is not an OOM, timeout, replica restart, or platform eviction

- timestamp: 2026-09-13T14:27:12+08:00
  checked: publication lifecycle evidence
  found: no table publication, table write, Gold staging, or pointer activation events; authenticated server/AUM endpoint remains 503 because the Silver patch snapshot is incomplete
  implication: no successful barrier or readable pointer was committed by this execution

- timestamp: 2026-09-13T14:31:10+08:00
  checked: project scope, skill configuration, worktree status, and debug knowledge base
  found: Phase 4 explicitly retains the exact container evidence/publication gate; no debugger agent skills are configured; the sole project skill is `archify`; prior KB entries concern earlier ontology atomicity and high-payload APPEND failures but no entry matches this post-container/pre-ontology-construction stage; unrelated tracked and untracked worktree changes pre-exist
  implication: the investigation is in scope, must preserve unrelated changes, and should treat prior scale failures only as tested candidates rather than assume recurrence

- timestamp: 2026-09-13T14:33:20+08:00
  checked: initial repository symbol/history scan
  found: ontology/activation history includes exact replay commit `a59bfa3c5`, replay hardening through `89fcb0102`, source-partition deduplication `ce9a97161`, and ontology predecessor atomicity `1132705ff`; the broad symbol search found relevant tests but was too large to establish a boundary
  implication: source/historical differential analysis should concentrate on these recent changes and exact definitions rather than infer from the stage log alone

- timestamp: 2026-09-13T14:35:10+08:00
  checked: exact symbol location scan
  found: the granular mapper is `src/fabric/dataset_mapper.py:714`; `FabricSyncService` calls `build_rows` at line 852, entity merge at 858, relationship merge at 862, and emits `ontology_construction` only at 879; merge helpers are at lines 3517 and 3578
  implication: absence of the stage-start event narrows the executable region to fewer than 30 lines and makes each candidate independently testable

- timestamp: 2026-09-13T14:38:20+08:00
  checked: exact pre-stage call sequence and mapper configuration
  found: after container completion the code executes mapper build, entity merge, relationship merge, then copies `temporal.all_observation_rows` with `list(...)`, deletes intermediates, and only then emits ontology construction start; the mapper's EntityBuilder caps source rows/entities at 100000 and RelationshipBuilder caps entities at 100000 and relationships at 250000
  implication: all four requested stages are now distinguished; cardinality enforcement in build is a direct deterministic candidate, while the observation copy has no explicit invariant check and would require an ordinary Python allocation failure

- timestamp: 2026-09-13T14:42:00+08:00
  checked: granular mapper and EntityBuilder implementation
  found: `EntityBuilder.build` eagerly converts source rows to a list and raises exactly `ValueError("Ontology source rows exceed configured bound")` when count is greater than 100000; granular source construction validates all cross-table references first, then appends one source row per registry, logical image, digest, current exposure, deployment, plus one deduplicated CVE Weakness row
  implication: mapper cardinality is a precise falsifiable invariant; production can exceed the mapper cap even when the emitted container table aggregate itself is below 100000 because CVE ontology nodes are additive

- timestamp: 2026-09-13T14:45:10+08:00
  checked: remainder of granular source-row construction and activation replay path
  found: each workload deployment appends both a `WorkloadDeployment` source row and a separate `KubernetesCluster` source row before EntityBuilder deduplication; `activate_runtime` re-verifies and passes an exact immutable retained generation to `FabricSyncService.sync`, and remote snapshot resolution is read-only under `source_root/generations/{source_run_id}`
  implication: exact mapper source cardinality is `R+L+D+E+2W+C`, and the retained snapshot provides a production-faithful no-publication reproduction input if loaded without calling `sync`

- timestamp: 2026-09-13T14:48:20+08:00
  checked: container materialization and stage-progress count
  found: `materialize_container_exposure_tables` returns only `gold_container_exposure_current` plus exactly one `gold_container_exposure_coverage` row; the logged container entity_count is the sum of only those returned tables
  implication: the production completion count 87241 proves exactly 87240 current exposure rows, so the mapper has only 12760 rows of headroom for all registries, logical images, digests, twice-counted deployment source rows, and unique CVEs

- timestamp: 2026-09-13T14:51:10+08:00
  checked: read-only Container Apps execution and current job metadata
  found: failed execution snapshot used the expected immutable image digest with 4 CPU/16Gi and zero retries; current job configuration is restored to Manual, 4 CPU/8Gi, timeout 3600, retry limit zero
  implication: environment restoration constraints remain satisfied and the failed run had enough headroom that a caught deterministic ValueError is more consistent than OOM

- timestamp: 2026-09-13T14:54:20+08:00
  checked: deployment source configuration and failed execution replica retention
  found: production source data root is a retained OneLake `Files/aiops/inventory-source` path; the terminated execution no longer exposes a replica via Azure CLI, while the immutable job execution record remains Failed
  implication: direct retained-snapshot inspection is the stronger reproduction path; fetching container logs by replica is no longer available and is not required if source replay reproduces

- timestamp: 2026-09-13T14:58:20+08:00
  checked: granular mapper history
  found: commit `ac556cc26` explicitly raised granular limits to 250000 source rows, 300000 entities, and 1000000 relationships to support the live 150k-observation Defender corpus; current code instead fixes all mapper/entity limits at 100000 and relationships at 250000
  implication: the current 100000 cap is a historical regression candidate, not an original intentional production-scale limit; the lowering commit and retained cardinality must still be proven

- timestamp: 2026-09-13T15:02:20+08:00
  checked: blame and lowering commit
  found: commit `4199bb61bd` lowered the granular source cap from 250000 to 100000 and reverted entity/relationship/synchronizer capacities to defaults while canonicalizing raw observations into current exposures; its tests assert configured constants but do not construct an N/N+1 production-cardinality input
  implication: this is a deterministic Bohrbug candidate introduced by an untested cardinality assumption; SBFL is unavailable because no existing test fails on the retained production equivalence class

- timestamp: 2026-09-13T15:07:10+08:00
  checked: current retained OneLake activation manifest through read-only Azure CLI-authenticated filesystem access
  found: active immutable generation `activation-0a9b3cff-e059-44b9-bbd2-4d9aca0eb3fc` completed at 2026-09-13T05:11:05Z inside the failed execution window and declares 12 logical images, 1046 image digests, 163821 vulnerability observations, zero workload deployments, and 18 workload checkpoints
  implication: this is the exact failed source generation with no later activation; zero deployments removes the doubled-deployment term, so unique-CVE count or another invariant must be measured before confirming the 100000 bound

- timestamp: 2026-09-13T15:19:20+08:00
  checked: isolated read-only mapper reproduction against the exact retained generation
  found: reconstruction produced 3 registries, 12 logical images, 1046 digests, 163821 raw observations, 87240 canonical current exposures, zero deployments, and 652 unique CVEs; exact granular source count was 88953, below 100000, but `GranularExposureOntologyMapper.build_rows` raised `ValueError: Ontology relationship bound exceeded`
  implication: source-row and entity limits are eliminated as the immediate exception; failure is inside RelationshipBuilder invoked by `build_rows`, before entity merge, relationship merge, and observation copy

- timestamp: 2026-09-13T15:22:50+08:00
  checked: RelationshipBuilder typed-image rules and downstream synchronizer
  found: every canonical VulnerabilityObservation emits three unique relationships at lines 404-406 (`affects` digest, `identifies` CVE, and reverse `hasVulnerabilityObservation`); 87240 observations therefore require 261720 edges before image/registry/structural edges, already above the 250000 default; `_synchronize_ontology` later constructs another default-capped `OntologyGraphSynchronizer`
  implication: the exact algorithmic failure is a deterministic 3× fan-out versus a 250000 cap, and changing only the mapper builder bound would expose a second downstream 250000-cap failure

- timestamp: 2026-09-13T15:27:30+08:00
  checked: raised-cap exact retained granular graph
  found: with only the in-memory relationship cap raised to 1000000, the exact retained input builds 88959 entities and 262786 relationships: 87240 each of `affects`, `identifies`, and `hasVulnerabilityObservation`, 1046 `hasDigest`, 12 `containsImage`, 6 `contains`, and 2 `owns`
  implication: the default cap is exceeded by exactly 12786 relationships; the three-edge canonical observation fan-out alone accounts for 261720 and proves the mechanism independently of merge behavior

- timestamp: 2026-09-13T15:31:20+08:00
  checked: first full-merge harness attempt
  found: the temporary default dependency environment could not import `fabric.sync_service` because optional `pydantic` was absent; failure occurred before retained data access or any merge
  implication: this is a harness dependency issue, not evidence for or against entity/relationship merge correctness; rerun with the repository's relevant dependency extra

- timestamp: 2026-09-13T15:34:10+08:00
  checked: second full-merge harness startup
  found: API dependencies installed, but the editable package layout omitted nested `agents.operations`; failure again occurred during import before data access
  implication: rerun with the repository `src` directory explicitly on `PYTHONPATH`; no bug hypothesis changed

- timestamp: 2026-09-13T15:41:20+08:00
  checked: exact retained full-graph merge and raised-cap synchronization
  found: base ontology contained 2066 entities/855 relationships; entity merge succeeded at 91017 entities; relationship merge succeeded at 263634 relationships; `OntologyGraphSynchronizer` with 300000/1000000 bounds validated and synchronized the merged graph with quality report passed
  implication: entity merge and relationship merge are correct for the exact production data, total entities fit the current 100000 cap, and only relationship capacity blocks the graph; post-merge observation copy was never reached in the failing path

- timestamp: 2026-09-13T15:45:40+08:00
  checked: downstream synchronization/reader limits and ontology contract
  found: `_synchronize_ontology` creates a default `OntologyGraphSynchronizer` capped at 250000 relationships; deployed `fabric.semantic.max_relationship_rows` is also 250000 and `SemanticEngine.from_rows` rejects any larger list; the accepted vocabulary explicitly includes all three observation edges, including the reverse edge
  implication: removing an edge would change the accepted ontology contract, while raising only the first builder cap is incomplete; the minimum safe remediation must align builder, publication synchronizer, and deployed semantic reader capacity

- timestamp: 2026-09-13T15:48:10+08:00
  checked: ACR metadata for the exact execution image digest
  found: digest `sha256:810389...dec6090` was created at 2026-09-13T03:22:40Z and is tagged `main-01a9aaf2e`
  implication: the deployed source revision can be compared directly with the identified regression commit rather than assuming the worktree matches the image

- timestamp: 2026-09-13T15:52:30+08:00
  checked: deployed revision ancestry and deployed source contents
  found: ACR tag commit `01a9aaf2e` descends from `4199bb61bd`; the deployed revision contains `default_factory=RelationshipBuilder` at dataset_mapper.py:729-731, the three edge emissions at relationship_builder.py:404-406, and the default-capped synchronizer at sync_service.py:2438
  implication: code/image skew is eliminated; the exact failing algorithm and limits were present in the deployed image

## Eliminated

- hypothesis: D4/16Gi memory exhaustion caused the failure
  evidence: peak memory remained below 7GiB and the replica had zero restarts
  timestamp: 2026-09-13T14:27:12+08:00

- hypothesis: publication timed out
  evidence: execution failed after approximately 4678 seconds while the temporary timeout was 7200 seconds
  timestamp: 2026-09-13T14:27:12+08:00

- hypothesis: granular source rows exceeded the 100000 EntityBuilder input bound
  evidence: exact retained-generation reconstruction produced 88953 source rows and passed source construction before failing in RelationshipBuilder
  timestamp: 2026-09-13T15:19:20+08:00

- hypothesis: entity merge, relationship merge, or post-merge observation copy caused the failure
  evidence: isolated `GranularExposureOntologyMapper.build_rows` fails first with `Ontology relationship bound exceeded`, so sync_service.py never reaches lines 858, 862, or 866
  timestamp: 2026-09-13T15:19:20+08:00

## Resolution

root_cause: "AND-gated regression: commit `4199bb61bd` canonicalized 163821 raw observations into 87240 current digest-CVE observations but simultaneously lowered granular relationship capacity from 1000000 to 250000. Each current observation emits three required v2 edges, so the exact generation needs 262786 granular relationships and the merged graph needs 263634; `RelationshipBuilder.connect` raises at the 250001st unique edge inside `GranularExposureOntologyMapper.build_rows`."
fix: "Not applied (diagnose-only). Smallest production-safe direction: preserve all accepted v2 edges; establish one shared bounded publication capacity with headroom (restore the prior 1000000 relationship bound), use it in GranularExposureOntologyMapper's RelationshipBuilder and synchronizer, use the same bound in FabricSyncService._synchronize_ontology, and set deployed semantic.max_relationship_rows to the same value. Do not change source/entity bounds merely to address this incident."
verification: "Derived oracle. Exact retained generation was read without writes; default mapper reproduced `Ontology relationship bound exceeded`; an in-memory 1000000 relationship cap produced 88959 entities/262786 granular relationships; exact entity and relationship merges produced 91017/263634 and raised-cap synchronization passed validation. No production fix or publication was executed."
files_changed:

## Specialist Review

specialist_hint: python
verdict: SUGGEST_CHANGE
review: "The remediation direction is correct, but relationship capacity must be genuinely single-sourced rather than copied across defaults. Define one shared 1000000 capacity and apply it to the mapper builder and synchronizer, FabricSyncService synchronization, semantic defaults, FabricSemanticConfig, and deploy/example YAML. Preserve all three ontology-v2 edge types. Test N-1/N/N+1, merged synchronization including retirements, retained replay, exact edge types, and config/default parity."
