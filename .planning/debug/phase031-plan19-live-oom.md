---
status: diagnosed
trigger: "Diagnose the Phase 03.1 Plan 19 live activation OOM scientifically, without modifying code. Repo: /Users/jasonmba/workspace/azure-aiops, branch main. Integrated image aiops-api:phase031-integrated-20260907-2240 ran `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` in Azure Container Apps Job with 2 CPU/4Gi. Execution aiops-dev-exposure-publication-ows94mn ran 2026-09-07 14:54-14:58 UTC and terminated exit 137. Console logs only show Cost Management 429 handled as non-fatal; no subsequent logs. Prior 1Gi job also OOM'd. Live ARG has ~21k microsoft.security/assessments. Need identify likely exact memory amplification/retained-object path in activation -> ingestion -> snapshot -> Fabric sync/ontology. Inspect code and existing tests only; report evidence with file/line references, primary root cause, minimal production-safe fix, and targeted tests. Respect concurrent ownership: do not edit src/fabric/dataset_mapper.py, src/fabric/sync_service.py, src/fabric/runtime.py, remediation files. Do not modify any files."
created: 2026-09-07T23:02:19.059+08:00
updated: 2026-09-08T21:12:00+08:00
---

## Current Focus

hypothesis: confirmed separately — Exposure Gold 503 remains the blocking missing-readable-generation lifecycle issue; Foundry provider emptiness is the intended fail-closed `legacy_unversioned`/`compatibility` release state, so inventory correctly returns deterministic fact-only narration
test: complete — source/provider/activation call graphs, Terraform deployment and promotion contracts, Phase 11 release intent, sanitized live revision metadata, focused tests, history, and working-tree ownership all agree
expecting: no Foundry mutation is included in bounded Gold recovery; any future Foundry activation follows its independently governed publish/validate/promote deployment workflow
next_action: return diagnose-only root cause and classification with no source/config/cloud mutation
bug_class: bohrbug
known_pattern_candidate: `foundry-portal-model-support` — prior Foundry setup required a portal-compatible model/tool combination, but this is only a candidate and does not establish that this release owns agent creation
candidate_causes:
  - code/lifecycle: post-deploy activation owns Foundry prompt-agent creation or restoration but has not completed
  - config/environment: operations-copilot and specialist provider IDs are intentionally or accidentally absent from the API revision
  - release contract: Foundry is optional and deterministic compatibility fallback is the intended unconfigured behavior
  - data/state: a prompt agent exists externally but its identifier is not wired into API configuration
and_gate: no for symptom production — an empty optional provider is sufficient to select fallback; whether configuration is a release defect depends independently on the documented deployment/activation contract
blocking_issue: Exposure Gold 503 remains the release blocker with its already-confirmed missing readable-generation lifecycle state; Foundry narration is being classified independently and will not be included in bounded Gold recovery unless source proves a shared required activation contract

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

- hypothesis: Bounded onboarding/Gold activation is expected to create, restore, or configure the Foundry operations-copilot prompt agent.
  evidence: `activate_runtime` contains only connection validation/discovery, combined snapshot publication, Fabric sync/Exposure pointer activation, and semantic verification; all Foundry creation/promotion is isolated in Terraform plus a data-plane POST script and requires separate staged applies.
  timestamp: 2026-09-08T21:12:00+08:00

- hypothesis: Empty copilot and specialist providers indicate accidental endpoint/name deployment drift.
  evidence: the live revision has a configured Foundry endpoint, coordinator name, and eight specialist names, but intentionally reports `legacy_unversioned`, version pinning `true`, zero version IDs, and Copilot rollout `compatibility`; this exact state is required by Phase 11-05 and focused tests.
  timestamp: 2026-09-08T21:12:00+08:00

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

- timestamp: 2026-09-08T20:36:00+08:00
  checked: activation CLI and complete activation runtime
  found: `--connection-id` is appendable and defaults to all active only when omitted; activation validates and syncs each selected connection, publishes one combined snapshot, then calls Fabric sync with `exposure_pointer_store=OneLakeDocumentStore(service.registry.root)`
  implication: the recovery must pass an explicit minimal complete connection set and cannot replace the full activation with a pointer-only write or a Fabric-only command

- timestamp: 2026-09-08T20:36:00+08:00
  checked: deploy connector config, Dockerfile, and onboarding runtime
  found: the final image bakes `arg.config.deploy.yaml` at `/app/config.yaml`; its output root inherits the Job's OneLake `AIOPS_HOME`, and per-connection ingestion writes beneath that same root before combined publication
  implication: the owner command should retain the deployed config paths and root/identity, changing only the Job image if preflight proves all other frozen template fields match

- timestamp: 2026-09-08T20:43:00+08:00
  checked: live OneLake subscription registry document
  found: registry revision 2115 contains exactly one connection, `demo`, active, for subscription `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`
  implication: the smallest complete and deterministic selector is exactly `--connection-id demo`; omitting it would introduce future registry growth into the run boundary

- timestamp: 2026-09-08T20:43:00+08:00
  checked: target ACR tag and current Job template
  found: `integrated-main-b2ba7558-20260908-1833` resolves to `sha256:29c8c2038052367b5b21984c668d8975313550b4015e22b5279178c706b06cd8`; current Job template is manual, 4 CPU/8 GiB, timeout 3600, retry 0, parallelism/completion 1, command `python -m onboarding.cli activate ... --connection-id demo`, but points to old digest `sha256:14e76a75...`
  implication: only the persistent template image needs changing before one plain start; all sizing, identity, root, and command fields are already correct

- timestamp: 2026-09-08T20:43:00+08:00
  checked: latest final-image execution `aiops-dev-exposure-publication-vupbscq`
  found: its frozen execution override used the final tag but defaulted to 0.5 CPU/1 GiB and had null command/args, then Failed; it did not inherit the Job's 4 CPU/8 GiB activation template
  implication: do not use `az containerapp job start --image ...` with partial overrides; update and verify the persistent template first, then start with no execution overrides

- timestamp: 2026-09-08T20:50:00+08:00
  checked: all six actual flat OneLake table prefixes derived from `OneLakeWriter.table_uri` and `_table_name`
  found: `Tables/gold_exposure_facts`, dimensions, facets, summaries, evidence each contain two blobs, and `Tables/metadata_exposure_gold_generations` contains three; the earlier zero-blob check used the wrong nested prefix `Tables/gold/gold_exposure_facts`
  implication: revoke the earlier inference that no Gold products were staged; pointer/fallback absence remains directly proven, but recovery preflight must permit retained staged Delta artifacts and must not attempt cleanup

- timestamp: 2026-09-08T21:02:00+08:00
  checked: staged Gold Delta blob timestamps and sanitized metadata parquet row
  found: all flat Gold tables were initialized on 2026-09-07 around 07:12 UTC; the five product tables contain only their initial Delta logs, while metadata contains one reconciled `inventory-refresh` row with no previous generation and seven-day retention
  implication: this is a legacy empty staged baseline, not a readable generation; it must be retained and idempotently merged by full activation, not manually activated, deleted, or treated as a rollback predecessor

- timestamp: 2026-09-08T21:02:00+08:00
  checked: target source ancestry and final pointer/result contracts
  found: memory fix `88ad45393` is an ancestor of target commit `b2ba7558`; successful current source emits `exposure-gold-` plus 24 hex characters, writes five Gold product tables and generation metadata, then creates schema 1.0.0 pointer revision 1 with null previous generation, two-generation/seven-day retention policy, and zero activation conflicts
  implication: exact success can be asserted without guessing row count by matching execution image/resources, pointer schema/revision/generation, and API `knowledge_version`/`data.generation`

- timestamp: 2026-09-08T21:03:00+08:00
  checked: user-provided additional live evidence
  found: inventory is healthy with 2 machines and 35 software observations, while narration reports `no Foundry prompt agent is configured`; API logs report empty copilot and all specialist agent providers
  implication: inventory acquisition health is independent of Foundry provider construction; the narration fallback must be classified from the optional-provider/deployment contract rather than conflated with the separately blocking Exposure Gold 503

- timestamp: 2026-09-08T21:04:00+08:00
  checked: knowledge base, initial exact-text/provider search, and working-tree ownership
  found: the knowledge base has a prior `foundry-portal-model-support` entry showing Foundry setup has an external model/tool compatibility constraint; the exact provider seam is declared in `src/api/dependencies.py`; pre-existing `.azure/deployment-plan.md` and `.azure/validate-status.json` changes remain untouched, and this continuation has changed only the permitted debug document
  implication: external Foundry provisioning is a plausible independent lifecycle, but the prior match is only a hypothesis candidate; source and release contracts must establish whether post-deploy activation owns it

- timestamp: 2026-09-08T21:05:00+08:00
  checked: targeted Foundry provisioning and Terraform wiring search
  found: `infra/scripts/create-foundry-agent.sh` explicitly describes an idempotent create/update of a data-plane-only prompt agent invoked by a Terraform `local-exec` provisioner; `infra/terraform/container_apps.tf` wires dynamic specialist environment values from a Foundry promotion/rollback activation map
  implication: agent provisioning is a distinct cloud mutation seam owned by deployment infrastructure, not yet evidence of an onboarding activation side effect; empty API providers can result from promotion/configuration state independently of Exposure Gold

- timestamp: 2026-09-08T21:06:00+08:00
  checked: API composition and Foundry client construction
  found: `ApiContext` documents the narrator as optional by design and missing specialists as optional; `FoundryPromptAgent.from_env` and the MAF adapter both return `None` when endpoint/name are absent, explicitly to allow retrieval-only operation; `_load_foundry_agent` logs that outcome and memoizes it rather than trying to provision anything
  implication: empty providers are a supported deterministic runtime state, not an initialization exception; runtime provider construction is read-only and cannot restore an agent

- timestamp: 2026-09-08T21:06:00+08:00
  checked: exact live fallback text
  found: the literal `Risk narrative unavailable: no Foundry prompt agent is configured` is emitted only by `src/intelligence/inventory/narrative.py`, not by the blocking Exposure generation path
  implication: the reported narration symptom is the inventory narrative's explicit compatibility branch and is causally separate from Exposure Gold 503

- timestamp: 2026-09-08T21:07:00+08:00
  checked: complete inventory narrative fallback implementation
  found: the route always computes deterministic scoped facts, citations, confidence, and source status first; when the optional Foundry agent is `None`, it returns `status: fact_only`, leaves `narrated_summary` empty, and appends the exact warning without turning healthy inventory into an error
  implication: the observed 2-machine/35-software response plus warning is the specified successful compatibility behavior, not partial inventory activation

- timestamp: 2026-09-08T21:07:00+08:00
  checked: onboarding activation implementation
  found: `activate_runtime` validates selected connections, performs discovery, publishes the combined snapshot, runs Fabric sync with the Exposure pointer store, and reads semantic readiness; it imports or invokes no Foundry client, Terraform, provisioning script, agent endpoint, or API environment update
  implication: bounded Gold recovery cannot create, restore, promote, or configure an operations-copilot prompt agent

- timestamp: 2026-09-08T21:07:00+08:00
  checked: Terraform Foundry promotion and API wiring contracts
  found: candidate agent publication requires `create_foundry_agent && enable_foundry_specialist_candidate_publish`, version-pinning verification, and a persistent promotion artifact; it POSTs immutable versions through `local-exec`, validates parity, and only a later Terraform plan may activate provider IDs. Defaults retain `legacy` unversioned names and `compatibility` Copilot rollout, while runtime version pinning deliberately converts an unversioned selection into unavailable providers
  implication: any attempt to restore/configure Foundry is an independent cloud mutation and staged deployment decision, not a side effect or prerequisite of the one bounded Exposure publication

- timestamp: 2026-09-08T21:08:00+08:00
  checked: focused inventory and agent contract tests
  found: tests require an unconfigured inventory narrative to return HTTP 200 with scoped source counts, `status: fact_only`, deterministic facts, and the `no Foundry` warning; separate tests require provider construction to return `None` when version pinning is required but legacy names have no provider version IDs
  implication: the exact live behavior has executable regression coverage and is not an accidental error-handling path

- timestamp: 2026-09-08T21:08:00+08:00
  checked: committed Terraform deployment inputs
  found: `infra/terraform/terraform.tfvars` explicitly sets `foundry_version_pinning_runtime_verified = true` and supplies no override for `foundry_specialist_activation_target`, `enable_foundry_specialist_candidate_publish`, or the promotion artifact; their defaults are respectively `legacy`, `false`, and empty
  implication: the committed release intentionally combines fail-closed version pinning with an unpromoted legacy mapping, which makes all unversioned Foundry providers unavailable while retaining deterministic compatibility behavior

- timestamp: 2026-09-08T21:09:00+08:00
  checked: Phase 11-05 release summary and introducing history
  found: the closeout states verbatim that `legacy` activation omits versions and fails closed to deterministic evidence, candidate publication is disabled by default, live specialist parity is BLOCKED with promotion held, and staged adoption requires a later opt-in publication/validation apply followed by another reviewed activation apply
  implication: unavailable Foundry providers are the declared current release posture, not a failed bounded post-deploy activation; full Foundry enablement is pending a separately governed multi-apply rollout

- timestamp: 2026-09-08T21:10:00+08:00
  checked: sanitized read-only live API revision environment
  found: active revision `aiops-dev-api--0000268` reports activation source `legacy_unversioned`, version pinning `true`, orchestration mode `maf`, Copilot rollout `compatibility`, configured project endpoint and `operations-copilot` name, but no coordinator version and zero specialist version variables (eight legacy specialist names remain)
  implication: live provider emptiness is exactly the intentional fail-closed staged-adoption state; it is not endpoint/name drift and cannot be repaired by onboarding activation

- timestamp: 2026-09-08T21:11:00+08:00
  checked: focused local verification
  found: seven tests passed covering inventory HTTP-200 fact-only fallback, unversioned rejection under required pinning, acceptance of a pinned coordinator, complete synthesis without Foundry, legacy activation fallback, opt-in candidate publication, and omission of synthetic legacy versions
  implication: source, infrastructure contract, and live revision state agree; no code/config mutation is warranted for the current Foundry behavior

- timestamp: 2026-09-08T21:12:00+08:00
  checked: final scope and mutation consistency
  found: `.planning/STATE.md` still identifies Plan 03.1-19 Exposure live evidence as the active blocker; Phase 11-05 explicitly records that no live agent version was promoted and deterministic fallback is preserved; pre-existing `.azure` changes remain untouched and this investigation changed only the permitted debug document
  implication: Foundry must remain a non-blocking separately staged capability, while the bounded recovery scope stays limited to successful Exposure Gold publication

- timestamp: 2026-09-08T21:20:00+08:00
  checked: failed exact-template execution and Log Analytics
  found: execution `aiops-dev-exposure-publication-xejd3lo` ran the final image with the intended activation command, `demo` connection, managed identity, and 4 CPU / 8 GiB; Cost Management HTTP 429 degraded non-fatally, then activation terminated after approximately 35 minutes with `Invalid ontology graph: current snapshot validation failed`
  implication: missing pointer initialization remained the serving symptom, but the immediate publication blocker was deterministic ontology validation rather than memory, cursor, identity, or Fabric root drift

- timestamp: 2026-09-08T21:24:00+08:00
  checked: read-only reconstruction from the durable live `demo` connection generation
  found: the base graph passed at 1,979 entities / 882 relationships and the granular Exposure graph passed at 78,720 / 232,337; their raw union failed with 8 duplicate entity IDs and 7 duplicate relationship IDs/keys for tenant, subscription, three resource groups, and three container registries
  implication: `FabricSyncService` raw-extended two independently valid projections that intentionally share canonical scope/resource identities; live data was valid and the merge seam was defective

- timestamp: 2026-09-08T21:30:00+08:00
  checked: collision-preserving source fix and reconstructed live graph
  found: granular entity collisions now require compatible scope/type/lifecycle, preserve canonical inventory representation, merge non-conflicting embedded Fabric rows, union lineage, and recompute stable versions; relationship collisions require semantic equivalence, union lineage, and otherwise fail closed. The reconstructed graph passes at 80,691 entities / 233,212 relationships with all validator categories zero, and all 3 source registry rows round-trip exactly from ontology.
  implication: the fix removes the production blocker without discarding inventory context, granular Fabric reconstruction evidence, or conflicting relationship evidence

- timestamp: 2026-09-08T21:34:00+08:00
  checked: automated regression and independent review
  found: Ruff passed, the full backend suite passed with 3,947 tests, focused ontology tests passed, `git diff --check` passed, and final independent review found no blocking correctness issue after relationship evidence-conflict and lineage/version tests were added
  implication: source is ready for stabilization and a new immutable build, but the live blocker remains open until a successful publication creates the readable Gold pointer and the API returns 200

## Resolution

root_cause: "BLOCKING — Exposure Gold: `FabricSyncService` combined the independently valid base inventory ontology and granular Exposure ontology with raw list extension. Canonical tenant/subscription/resource-group/registry scope rows intentionally overlap, producing 8 duplicate entities and 7 duplicate relationships in the live graph. Validation failed before Gold stage/pointer CAS, leaving both readable-generation sources absent and the overview correctly fail-closed at 503. SEPARATE/NON-BLOCKING — Foundry narration remains the intentional `legacy_unversioned` compatibility posture."
fix: "Applied locally, not yet deployed: replace raw granular extension with explicit collision-aware merges. Compatible entity collisions retain canonical inventory fields, merge lossless granular Fabric payloads and lineage, and recompute stable versions; compatible relationship collisions union lineage and recompute versions, while identity/evidence conflicts fail closed. Foundry remains outside this recovery boundary."
verification: "Rebuilt the failed live input read-only from the durable `demo` generation. The fixed combined graph passes at 80,691 entities / 233,212 relationships with zero duplicates, dangling/self links, or invalid rows; all 3 registry rows round-trip exactly. Ruff, 3,947 backend tests, focused ontology regressions, whitespace checks, and independent correctness review passed. Live resolution still requires a new immutable image, one exact-template 4 CPU / 8 GiB publication, pointer/Gold verification, and overview 200."
files_changed:
  - "src/fabric/sync_service.py"
  - "src/ontology/entity_builder.py"
  - "src/ontology/relationship_builder.py"
  - "tests/test_fabric_sync_service.py"
