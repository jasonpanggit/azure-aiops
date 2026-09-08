---
status: diagnosed
trigger: "Diagnose the Phase 03.1 Plan 19 live activation OOM scientifically, without modifying code. Repo: /Users/jasonmba/workspace/azure-aiops, branch main. Integrated image aiops-api:phase031-integrated-20260907-2240 ran `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` in Azure Container Apps Job with 2 CPU/4Gi. Execution aiops-dev-exposure-publication-ows94mn ran 2026-09-07 14:54-14:58 UTC and terminated exit 137. Console logs only show Cost Management 429 handled as non-fatal; no subsequent logs. Prior 1Gi job also OOM'd. Live ARG has ~21k microsoft.security/assessments. Need identify likely exact memory amplification/retained-object path in activation -> ingestion -> snapshot -> Fabric sync/ontology. Inspect code and existing tests only; report evidence with file/line references, primary root cause, minimal production-safe fix, and targeted tests. Respect concurrent ownership: do not edit src/fabric/dataset_mapper.py, src/fabric/sync_service.py, src/fabric/runtime.py, remediation files. Do not modify any files."
created: 2026-09-07T23:02:19.059+08:00
updated: 2026-09-08T20:31:00+08:00
---

## Current Focus

hypothesis: confirmed — `_exposure_generation_window` has no readable identifier because the authoritative Gold pointer is absent and the active DatasetStore generation contains no fallback Exposure metadata; no Gold-capable publication execution has completed
test: complete — direct authenticated OneLake GET/list evidence checked both generation sources and Gold table prefixes; ARM/ACR/history identified the missing publication transition; focused local contract tests passed
expecting: diagnosis complete; no source or cloud mutation is authorized in this session
next_action: hand the smallest cloud-only initialization sequence to the owning Topology session for decision
bug_class: bohrbug
known_pattern_candidate: none found in .planning/debug/knowledge-base.md
candidate_causes:
  - code/lifecycle: final Gold-capable source was deployed to the API but no successful publisher execution initialized its readable pointer
  - config/environment: API and Job root/identity/cursor wiring drifted
  - data: Gold pointer and fallback Exposure metadata are absent
  - code: another generation-window dependency maps to the same 503
and_gate: no for the current 503 — one absent readable pointer is sufficient; unsuccessful publication is the leading cause, while root drift has been eliminated

## Symptoms

expected: activation completes within the Azure Container Apps Job limit of 2 CPU and 4 GiB
actual: integrated image aiops-api:phase031-integrated-20260907-2240 terminated with exit 137 after approximately four minutes; a prior 1 GiB job also OOM'd
errors: console logs show only a Cost Management HTTP 429 handled as non-fatal, with no subsequent logs; process termination exit 137
reproduction: run `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` against live Azure data where ARG contains approximately 21k `microsoft.security/assessments`
started: Phase 03.1 Plan 19 live activation execution at 2026-09-07 14:54–14:58 UTC; prior 1 GiB execution also failed by OOM

## Eliminated

- hypothesis: The publication Job writes the pointer to container-local `/app/live-data` because `/app/config.yaml` is the repository's local `config.yaml`.
  evidence: Dockerfile copies `arg.config.deploy.yaml` to `/app/config.yaml`; that deploy config intentionally omits `storage.output_dir` so it inherits remote `AIOPS_HOME`, and the Job has no volume mount overriding the file.
  timestamp: 2026-09-08T20:04:00+08:00

- hypothesis: API cursor-secret/KID Terraform drift causes the exact readable-generation 503.
  evidence: deployed API metadata shows both Key Vault-backed secret refs and distinct KIDs exactly wired; source produces the observed message before cursor processing and only from generation resolution.
  timestamp: 2026-09-08T20:04:00+08:00

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

- timestamp: 2026-09-08T19:00:00+08:00
  checked: active phase scope and exact local/deployed source identity
  found: `.planning/STATE.md` names Phase 03.1 / Plan 03.1-19 as the active blocked scope, and local `HEAD` is exactly `b2ba755804b8fa283adcfa39fca2bce1358c6edd`, matching the immutable deployed tag reported by the Topology session
  implication: the live readable-generation blocker is in scope and local source/history are an exact basis for read-only deployment diagnosis

- timestamp: 2026-09-08T19:00:00+08:00
  checked: knowledge base and working-tree ownership
  found: no knowledge-base entry matches the Exposure readable-generation 503; pre-existing `.azure/deployment-plan.md` and `.azure/validate-status.json` changes remain untouched, and this session has changed only the permitted debug document
  implication: no prior diagnosis can be assumed, and concurrent Topology ownership remains preserved

- timestamp: 2026-09-08T19:00:00+08:00
  checked: exact error/function search
  found: the exact message occurs at `src/api/runtime.py:3722` inside `_exposure_generation_window`; focused tests at `tests/test_api_runtime.py:81-127` cover both unavailable-without-generation and API-home-pointer fallback behavior
  implication: working backwards from this single fail-closed gate can distinguish generation data/pointer failure from unrelated asset-exposure serving behavior

- timestamp: 2026-09-08T19:07:00+08:00
  checked: `_exposure_generation_window` and focused runtime tests
  found: the function first reads `EXPOSURE_GOLD_POINTER_DOCUMENT` from `OneLakeDocumentStore(str(aiops_home()))`; if `readable_generation_id` is empty, it falls back to `EXPOSURE_METADATA_DATASET` and accepts only exactly one distinct non-empty `read_model_generation_id`; only when both paths fail does it raise the exact observed `Exposure readable generation is unavailable`
  implication: the live 503 is not a generic API failure and does not prove a stale referenced generation; it specifically proves that the API resolved no active generation identifier from either durable contract at request time

- timestamp: 2026-09-08T19:07:00+08:00
  checked: exposure query service composition and cursor dependency ordering
  found: `_fabric_exposure_query_service` constructs `ExposureCursorKeyRing.from_environment()` separately, while request-time `generation_window` calls `_exposure_generation_window`; the exact observed text originates only from the latter
  implication: missing cursor key material could break service construction or cursor operations but cannot map to this exact readable-generation 503, substantially disfavoring branch B's cursor-secret sub-branch

- timestamp: 2026-09-08T19:07:00+08:00
  checked: failure taxonomy and SBFL eligibility
  found: repeated identical live GETs fail with the same message while a sibling endpoint remains healthy; focused local tests specify the fail-closed branch but no local failing test reproduces the deployed durable state, so per-test failing/pass coverage is unavailable
  implication: classify the blocker as a deterministic environment/data-dependent Bohrbug; skip SBFL and use working-backwards plus deployment/source differential tracing

- timestamp: 2026-09-08T19:15:00+08:00
  checked: endpoint dependency differential
  found: `/vulnerabilities/exposure/overview` uses the Fabric SQL `exposure_query` provider and invokes its generation window, whereas `/vulnerabilities/asset-exposures` resolves the separate persisted/hybrid vulnerability service and never calls `_exposure_generation_window`
  implication: the sibling 200 is expected when general vulnerability data is healthy and does not imply Exposure Gold readiness; it narrows the blocker to the Gold query path

- timestamp: 2026-09-08T19:15:00+08:00
  checked: Terraform API environment contract at `infra/terraform/container_apps.tf:202-543`
  found: production API `AIOPS_HOME` points to the lakehouse `Files/aiops` root; cursor active/previous secrets and KIDs are separately wired; rollout generation IDs are deployment metadata, but `_exposure_generation_window` does not read those rollout variables
  implication: cursor-secret or rollout-ID drift is not the direct source of the exact message; the decisive environment value is the durable `AIOPS_HOME` root used for the pointer and fallback metadata

- timestamp: 2026-09-08T19:15:00+08:00
  checked: activation-to-Gold publication call graph
  found: `activate_runtime` performs discovery and combined snapshot publication, then uniquely calls `runtime.service.sync(exposure_pointer_store=OneLakeDocumentStore(service.registry.root))`; sync constructs Exposure temporal/Gold inputs only when that store is provided, stages five Gold tables plus generation metadata, and later calls pointer activation
  implication: deploying a healthy API image is not an initialization/migration event; a successful activation/sync with the pointer store is the source-owned transition that makes an Exposure generation readable

- timestamp: 2026-09-08T19:15:00+08:00
  checked: Gold publisher initial-state handling
  found: `ExposureGoldFabricPublisher.stage` explicitly accepts an empty pointer as revision 0 with no prior readable generation, persists reconciled generation-qualified tables, and `activate` CASes the readable pointer only afterward
  implication: final source already contains an initial publication path; there is no evidence yet that a separate pointer schema migration is required

- timestamp: 2026-09-08T19:24:00+08:00
  checked: first-publication, repeat-publication, rollback, and failed-finalization tests
  found: `tests/test_vulnerability_pipeline.py:478-536` proves the first publish has no previous generation and activates `gold-1`; `tests/test_fabric_sync_service.py:67-116` proves sync creates a deterministic pointer from an empty store; `tests/test_fabric_sync_service.py:151-168` proves finalization failure leaves the pointer exactly `{}`
  implication: source requires no initial migration; a missing pointer is the specified result of never completing the activation finalization boundary

- timestamp: 2026-09-08T19:24:00+08:00
  checked: sync ordering at `src/fabric/sync_service.py:727-822`
  found: Gold tables and generation metadata are staged first, but the readable pointer is activated only after normal table publication, ontology publication/catalog registration, a completed state write, and shortcut finalization; any exception before that final call prevents pointer activation
  implication: “Fabric publication succeeded” must mean the entire activation returned successfully, not merely that tables were written; staged Gold rows alone do not make the API readable

- timestamp: 2026-09-08T19:24:00+08:00
  checked: `OneLakeDocumentStore` read semantics
  found: remote not-found returns `{}`, and malformed JSON, OS errors, or Azure `HttpResponseError` are also suppressed to `{}` by ordinary `read`; `_exposure_generation_window` uses this suppressing read
  implication: the 503 alone cannot distinguish absent pointer data from wrong root/permission/transient OneLake read failure, so a direct read-only cloud check is required before collapsing branches

- timestamp: 2026-09-08T19:24:00+08:00
  checked: pointer activation CAS implementation
  found: `_activate` converts an empty revision-0 document into schema `1.0.0`, revision 1, with `readable_generation_id`, retention metadata, and the current generation retained; later CAS conflicts raise and do not silently activate
  implication: neither a pre-created document nor a standalone migration is a prerequisite for initial Gold activation

- timestamp: 2026-09-08T19:32:00+08:00
  checked: deployed Container App and Job inventory via read-only Azure CLI
  found: `aiops-dev-api` revision `aiops-dev-api--0000268` runs the reported final tag `integrated-main-b2ba7558-20260908-1833`, but `aiops-dev-exposure-publication` still references immutable digest `sha256:14e76a75...`; no cloud mutation was performed
  implication: the consolidated app deployment updated the reader but did not by itself update or execute the separate publication Job

- timestamp: 2026-09-08T19:32:00+08:00
  checked: relevant git history
  found: commit `89201567e` (`fix(exposure): publish reconciled Gold generations`) modified both `src/onboarding/activation.py` and the Gold pipeline on 2026-09-08 10:46 +08, after the reported 2026-09-07 14:54-14:58 UTC OOM execution; later `3d3b9d446` retained Exposure partition rows
  implication: the failed OOM execution could not have exercised the final source's current initial Gold pointer wiring, so a healthy reader deployment cannot reuse a pointer that run never created

- timestamp: 2026-09-08T19:32:00+08:00
  checked: onboarding root construction
  found: `ConnectorConfig.load` uses explicit `storage.output_dir` or falls back to `AIOPS_HOME`, and `build_onboarding_service` gives that exact `config.output_dir` to `ConnectionRegistry`; activation then uses `service.registry.root` for the pointer store
  implication: with production config omitting a divergent output root, publisher and API target the same `AIOPS_HOME`; deployed values still need read-only confirmation

- timestamp: 2026-09-08T19:42:00+08:00
  checked: exact deployed API environment and secret-reference metadata
  found: API revision `0000268` has the expected OneLake `AIOPS_HOME`, app managed-identity client ID, distinct active/previous cursor KIDs, and both cursor env variables referencing versionless Key Vault-backed `cursor-active`/`cursor-previous` secrets
  implication: branch B's API/cursor Terraform wiring is eliminated as the direct blocker; no secret value was read or exposed

- timestamp: 2026-09-08T19:42:00+08:00
  checked: exact publication Job template and ACR metadata
  found: the Job is provisioned with 4 CPU/8 GiB, the same app managed identity and remote `AIOPS_HOME`, command `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo`, and image digest `14e76a75...` tagged `phase031-gold-ac556cc26`
  implication: resource sizing and identity are explicit, but the command's config file can override `AIOPS_HOME`; the image is not the final `b2ba7558` deployment

- timestamp: 2026-09-08T19:42:00+08:00
  checked: publication Job execution history
  found: the last succeeded execution ran 2026-09-07 16:49-17:25 UTC, before the Sep 8 Gold-wiring commit; every later listed attempt is Failed or Stopped, including the `phase031-gold-ac556cc26` attempt started 2026-09-08 06:58 UTC
  implication: there is no successful execution evidence for the final initial-pointer activation path

- timestamp: 2026-09-08T19:42:00+08:00
  checked: repository connector config selected by the Job command
  found: `config.yaml` explicitly contains `storage.output_dir: ./live-data`; because explicit config wins over `AIOPS_HOME` and relative paths resolve beside `/app/config.yaml`, an unoverridden baked file would set the pointer root to `/app/live-data`
  implication: a potential publisher/API root drift exists despite both templates showing the same `AIOPS_HOME`; image/mount inspection is required to confirm whether the deployed Job actually uses this file content

- timestamp: 2026-09-08T20:04:00+08:00
  checked: Dockerfile, deployed Job mounts, and deploy connector config
  found: Dockerfile explicitly copies `arg.config.deploy.yaml` as `/app/config.yaml`; that deploy file intentionally leaves `storage.output_dir` unset to inherit `AIOPS_HOME`; the deployed Job has no volumes or mounts and supplies the same OneLake root as the API
  implication: the suspected pointer-root config drift is disproved; publisher and reader are designed and deployed against `Files/aiops`

- timestamp: 2026-09-08T20:04:00+08:00
  checked: deployed Job image source ancestry
  found: ACR tag `phase031-gold-ac556cc26` resolves to commit `ac556cc26f435694944d5aa22580cc047a03c010`, and `89201567e` is its ancestor
  implication: the latest Job image contains initial Gold publication support, but it only helps if an execution reaches successful finalization

- timestamp: 2026-09-08T20:04:00+08:00
  checked: latest stopped execution logs and first direct OneLake REST attempt
  found: Container Apps retained no replica logs accessible through `az containerapp job logs show`; the first DFS GET used an invalid query shape and therefore did not establish pointer presence or absence
  implication: both checks are inconclusive rather than negative evidence; use Log Analytics and corrected Blob/DFS GET semantics

- timestamp: 2026-09-08T20:12:00+08:00
  checked: corrected direct OneLake pointer reads via both Blob and DFS endpoints
  found: authenticated GETs to the deployed API root returned `BlobNotFound` and `PathNotFound` for `Files/aiops/exposure/gold-generation-pointer.json`
  implication: branch C is confirmed as missing, not stale or malformed pointer data; the API is not merely failing to parse an existing pointer

- timestamp: 2026-09-08T20:12:00+08:00
  checked: focused local generation contract tests
  found: all five targeted tests passed: missing-generation typed failure, API-home pointer read, first/rollback Gold publisher activation, repeatable sync pointer publication, and failed-finalization non-activation
  implication: final source behaves consistently with the traced mechanism and needs initialization state, not a source migration or speculative fix

- timestamp: 2026-09-08T20:12:00+08:00
  checked: commit `dd79802c3` history
  found: the commit only changed missing generation from an unhandled `RuntimeError`/500 into `ExposureQueryUnavailableError`/503; it did not create, migrate, or select a generation
  implication: the current 503 is an intentional diagnostic surfacing pre-existing absent state, not a regression introduced by exception mapping

- timestamp: 2026-09-08T20:20:00+08:00
  checked: complete OneLake `exposure/` prefix listing
  found: authenticated Blob enumeration returned an empty prefix, independently corroborating that no Gold pointer document or sibling Exposure document exists under the API's durable root
  implication: missing pointer data is definitive rather than a stale pointer to a deleted generation

- timestamp: 2026-09-08T20:20:00+08:00
  checked: ARM execution record for `aiops-dev-exposure-publication-ycjivod`
  found: status is exactly `Stopped`, end time is absent, and its frozen template confirms Gold-capable digest `14e76a75...`, 4 CPU/8 GiB, correct command, managed identity, and `AIOPS_HOME`
  implication: the only Gold-capable run has no completed publication outcome and cannot be treated as activation evidence

- timestamp: 2026-09-08T20:20:00+08:00
  checked: DatasetStore fallback implementation
  found: remote fallback resolves `Files/aiops/current.json`, then reads `generations/<selected>/vulnerability/exposure_metadata.jsonl`; a missing pointer, missing dataset, or non-singleton generation set yields no fallback active generation
  implication: the final discriminator is whether the active combined snapshot contains the compatibility metadata row; this does not alter the confirmed absence of the authoritative Gold pointer

- timestamp: 2026-09-08T20:27:00+08:00
  checked: live DatasetStore pointer
  found: `Files/aiops/current.json` exists and selects `inventory-activation-c6ed8adb-355d-4082-ab70-b8ea267b4e15`
  implication: general persisted inventory can remain healthy, explaining the sibling 200, while the separate Gold pointer is absent

- timestamp: 2026-09-08T20:27:00+08:00
  checked: live Gold table storage prefixes
  found: both `Tables/gold/gold_exposure_facts/` and `Tables/gold/metadata_exposure_gold_generations/` enumerate zero blobs
  implication: the stopped Gold-capable run did not even leave staged Gold products; this is an uninitialized publication, not a stale pointer referencing retained Gold data

- timestamp: 2026-09-08T20:27:00+08:00
  checked: retained Log Analytics summaries for later failed/stopped executions
  found: three earlier failed attempts have only four console lines each, while the latest `ycjivod` stopped execution has no retained console rows and ARM remains authoritative for its stopped status
  implication: logs cannot refine the stop cause, but no log evidence contradicts the durable-state proof that activation never reached Gold staging or pointer CAS

- timestamp: 2026-09-08T20:31:00+08:00
  checked: active DatasetStore fallback generation and manifest
  found: authenticated GET for `generations/inventory-activation-c6ed8adb-355d-4082-ab70-b8ea267b4e15/vulnerability/exposure_metadata.jsonl` returned `BlobNotFound`; its completed manifest has `readModelGenerationId: null`
  implication: the exact fallback branch in `_exposure_generation_window` also yields no active generation, completing the direct proof for the observed 503

- timestamp: 2026-09-08T20:31:00+08:00
  checked: final branch evaluation
  found: A/C confirmed — initial Gold activation has not completed and live pointer/fallback data are missing; B eliminated — API/Job share the correct root and identity and cursor refs are intact; D eliminated — the exact error has one source and both of its data branches were directly observed empty
  implication: no source migration or code fix is required for this blocker; the owning mutation lane must perform and verify one successful Gold-capable publication

## Resolution

root_cause: "The API is correctly failing closed because both readable-generation sources are absent: `Files/aiops/exposure/gold-generation-pointer.json` does not exist, and the active DatasetStore generation has neither `vulnerability/exposure_metadata.jsonl` nor a manifest `readModelGenerationId`. The causal lifecycle gap is that no execution containing the Sep 8 Gold activation wiring completed: older successful Jobs predate commit 89201567e, while the sole Gold-capable ac556cc26 execution is Stopped. This is initial Gold activation/publication missing state (A leading to C), not a migration, cursor-secret drift, stale pointer, or another source bug."
fix: "Not applied (diagnose-only). Smallest safe remediation for the owning Topology mutation lane: update/confirm `aiops-dev-exposure-publication` on the final immutable integrated image, start exactly one activation, require a Succeeded execution, then verify Gold facts/generation metadata and pointer revision/readable_generation_id before retrying the overview. Every Job template update and Job start is a cloud mutation."
verification: "Diagnosis verified read-only: exact deployed source/tag and env inspected; pointer GET returned BlobNotFound/PathNotFound; Exposure prefix and both Gold table prefixes were empty; fallback metadata GET returned BlobNotFound and active manifest generation was null; ARM showed the only Gold-capable execution Stopped; 5 focused local generation tests passed."
files_changed: []
