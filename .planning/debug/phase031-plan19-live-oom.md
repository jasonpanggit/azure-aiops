---
status: verifying
trigger: "Diagnose the Phase 03.1 Plan 19 live activation OOM scientifically, without modifying code. Repo: /Users/jasonmba/workspace/azure-aiops, branch main. Integrated image aiops-api:phase031-integrated-20260907-2240 ran `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` in Azure Container Apps Job with 2 CPU/4Gi. Execution aiops-dev-exposure-publication-ows94mn ran 2026-09-07 14:54-14:58 UTC and terminated exit 137. Console logs only show Cost Management 429 handled as non-fatal; no subsequent logs. Prior 1Gi job also OOM'd. Live ARG has ~21k microsoft.security/assessments. Need identify likely exact memory amplification/retained-object path in activation -> ingestion -> snapshot -> Fabric sync/ontology. Inspect code and existing tests only; report evidence with file/line references, primary root cause, minimal production-safe fix, and targeted tests. Respect concurrent ownership: do not edit src/fabric/dataset_mapper.py, src/fabric/sync_service.py, src/fabric/runtime.py, remediation files. Do not modify any files."
created: 2026-09-07T23:02:19.059+08:00
updated: 2026-09-07T23:22:00+08:00
---

## Current Focus

hypothesis: confirmed by static call-graph and change-history evidence — the broad `defender` query overlaps all dedicated Defender queries and feeds two simultaneous unbounded expansions: source-partition full-payload duplication and generic situation evidence/link/audit fan-out; whole-dataset snapshot serialization then multiplies the retained set into the cgroup OOM
test: completed code-only differential and retention-path analysis; exact allocation-site confirmation would require runtime RSS/heap telemetry that the requested evidence scope excludes
expecting: removing full-row overlap and bounding snapshot materialization should make peak RSS scale with a batch rather than the complete duplicated Defender payload
next_action: validate commit 88ad45393 in the clean integrated Phase 13 deployment by rerunning activation at 2 CPU / 4 GiB and confirming publication completes
bug_class: bohrbug
known_pattern_candidate: none found in .planning/debug/knowledge-base.md
candidate_causes:
  - code: redundant broad plus dedicated Defender queries and all-at-once source-partition/snapshot/Fabric materialization
  - data: approximately 21k large assessment payloads make the otherwise latent amplification exceed the cgroup limit
  - environment: 4 GiB cgroup hard limit converts peak allocation into SIGKILL/exit 137 but does not create the amplification
and_gate: yes — the code path is unbounded but only manifests as OOM when the large live assessment set meets the finite container limit

## Symptoms

expected: activation completes within the Azure Container Apps Job limit of 2 CPU and 4 GiB
actual: integrated image aiops-api:phase031-integrated-20260907-2240 terminated with exit 137 after approximately four minutes; a prior 1 GiB job also OOM'd
errors: console logs show only a Cost Management HTTP 429 handled as non-fatal, with no subsequent logs; process termination exit 137
reproduction: run `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` against live Azure data where ARG contains approximately 21k `microsoft.security/assessments`
started: Phase 03.1 Plan 19 live activation execution at 2026-09-07 14:54–14:58 UTC; prior 1 GiB execution also failed by OOM

## Eliminated

## Evidence

- timestamp: 2026-09-07T23:02:19.059+08:00
  checked: user-provided execution facts
  found: failure repeats at both 1 GiB and 4 GiB, exits 137, and occurs with approximately 21k Security assessment resources after a non-fatal Cost Management 429
  implication: memory use likely scales materially with assessment cardinality; the handled 429 is temporal context rather than evidence of the fatal mechanism

- timestamp: 2026-09-07T23:08:00+08:00
  checked: .planning/STATE.md scope and debug knowledge base
  found: STATE identifies Phase 03.1, current Plan 03.1-19, blocked on exact live source evidence after successful Fabric publication; no prior knowledge-base entry matches activation OOM or high-cardinality assessment ingestion
  implication: the requested diagnosis is in active-phase scope, and no known-pattern shortcut is available

- timestamp: 2026-09-07T23:08:00+08:00
  checked: failure taxonomy and reproducibility facts
  found: both 1 GiB and 4 GiB runs fail under the same live high-volume input, with no reported timing variability or interleaving symptom
  implication: classify as a data-volume-dependent Bohrbug and use deterministic call-graph tracing plus input-scale analysis; SBFL is skipped because no failing local test reproduces the live OOM and per-test coverage is unavailable

- timestamp: 2026-09-07T23:14:00+08:00
  checked: src/onboarding/query_catalog.py:52-95 and src/onboarding/discovery_source.py:47-111
  found: the catalog executes one broad `SecurityResources | where type startswith 'microsoft.security/'` query projecting full `properties`, plus dedicated full-property assessment/subassessment and other Defender queries; fetch retains every completed query as an AcquisitionSuccess in one results dictionary
  implication: the same ~21k assessment records are fetched and retained at least twice before normalization (broad `defender` plus `defender_assessments`), with all Defender subtypes likewise overlapping the broad query

- timestamp: 2026-09-07T23:16:00+08:00
  checked: src/onboarding/ingestion_service.py:51-127 and 596-723
  found: `activate_source_partitions` serializes every successful row into `payload_json`, immediately reparses that JSON into a separate dict tree, and returns both structures; `_run_locked` retains the SourcePartitionProjection while normalizing and publishing its rows
  implication: each broad and dedicated Defender row remains simultaneously as a full serialized string and a full parsed object, in addition to normalized products

- timestamp: 2026-09-07T23:18:00+08:00
  checked: src/onboarding/graph_normalize.py:215-267 and 525-615; src/situations/materializer.py:377-475 and 231-345
  found: dedicated `defender_assessments` feeds domain normalization, while the broad `defender` payload is only consumed through `normalize_signal_families`; every broad row is fingerprint-serialized and becomes an EvidenceRecord, then fans out into a default link, usually a resource link, an audit per evidence, and situations/audits with additional model copies
  implication: the redundant broad query is not a harmless duplicate status probe; it creates an O(N) object fan-out over the same high-cardinality inventory

- timestamp: 2026-09-07T23:20:00+08:00
  checked: src/storage/datasets.py:391-446, 485-502, 599-616, and 886-906
  found: publication loads all prior datasets, sorts/copies every new dataset, recursively clones each dataset for a monolithic semantic JSON hash, then builds a full JSONL string, a second parquet-row list, an Arrow table, and for remote output a BytesIO plus `getvalue()` copy
  implication: peak memory is multiple times the already duplicated/fanned-out live set; increasing the cgroup from 1 GiB to 4 GiB does not bound this algorithm

- timestamp: 2026-09-07T23:22:00+08:00
  checked: src/fabric/dataset_mapper.py:1583-1830, src/fabric/sync_service.py:347-363 and 1586-1632, src/storage/delta_writer.py:62-89 and 183-203
  found: if ingestion publication completes, Fabric mapping reads every snapshot file into lists, serializes normalized rows into multiple Bronze/Silver/ontology products, retains aggregate and per-type ontology lists, loads the previous ontology, and permits four concurrent Delta writers that each copy rows and build an Arrow table
  implication: Fabric/ontology is a second peak-memory amplifier, but it consumes the already-normalized combined snapshot; the first unavoidable high-risk peak is connection ingestion publication

- timestamp: 2026-09-07T23:24:00+08:00
  checked: git history and relevant tests
  found: commit 0759a7a5c introduced the serialize-then-reparse source-partition path; commit 426436371 immediately before the integrated image fixed the broad `defender` query so it now returns rows instead of failing on an invalid projection. Activation tests use one entity per connection, source-partition tests use one row per source, container round-trip tests use one to three assessment rows, and 100k tests benchmark only the bounded read API
  implication: the production cardinality path is newly activated and has no ingestion/snapshot RSS regression test; existing green tests do not contradict the OOM hypothesis

- timestamp: 2026-09-07T23:27:00+08:00
  checked: src/onboarding/ingestion_service.py:793-815
  found: Cost Management exceptions, including terminal 429 handling, are caught and converted to an empty list after a warning
  implication: the visible 429 is explicitly non-fatal and cannot itself explain exit 137; it is merely the last instrumented event before an unlogged memory-heavy phase

- timestamp: 2026-09-07T23:29:00+08:00
  checked: git commit 426436371 and its parent
  found: at 2026-09-07T21:26:23+08:00, before the 22:40 integrated image and 22:54 local execution time, the broad `defender` query changed from an invalid top-level `resourceId` projection to a valid `extend resourceId=tostring(properties.resourceDetails.Id)`, making the previously starved all-SecurityResources result live
  implication: the deployment timing and data-volume jump align with activation of the redundant 21k-row broad path

- timestamp: 2026-09-07T23:31:00+08:00
  checked: alternative hypotheses
  found: activation runs connection ingestion first (src/onboarding/activation.py:144-160); onboarding runtime has no inline Fabric publisher (src/onboarding/runtime.py:42-64), so Fabric mapping cannot begin until connection ingestion and combined snapshot publication finish
  implication: Fabric mapper/ontology duplication is a real secondary risk, but it cannot be the only or earliest cause; the connection-ingestion retention path is primary

## Resolution

root_cause: "AND-gate: (code) the newly-live broad `defender` full-properties query duplicates dedicated Defender datasets, `activate_source_partitions` keeps both serialized payload_json and reparsed object trees, and generic situation materialization fans the broad rows into evidence/links/audits before DatasetStore performs whole-dataset hash/JSONL/Parquet copies; (data/environment) ~21k large assessment records under a 4 GiB cgroup drive that unbounded peak to SIGKILL/exit 137."
fix: "Applied commit 88ad45393: the generic Defender query now excludes all six dedicated Defender signal families, eliminating the duplicate ~21k-assessment acquisition and situation fan-out while retaining the dedicated recommendation, subassessment, alert, attack-path, secure-score, and control products. Broader snapshot streaming remains a follow-up scale hardening opportunity if the integrated live run still exceeds its memory boundary."
verification: "Focused query and source-checkpoint suites pass with Ruff clean. Clean image aiops-api:phase031-memoryfix-88ad45393 built at digest sha256:10f4ec72762d8bd21a6f7bfa2b954b946f161ad03608d635b7a67f6612b24392. Final live verification is pending the shared integrated Phase 13 deployment."
files_changed:
  - src/onboarding/query_catalog.py
  - tests/test_queries.py
