---
phase: quick-260910-f2h
verified: 2026-09-10T03:58:43Z
status: human_needed
score: 7/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 7/8
  gaps_closed:
    - "Regression-confirmed: combined activation replay requires the exact queryVersion, unique non-empty sourceRunIds and sourceConnectionIds, and matching source-list cardinality before runtime or pointer construction."
    - "Full canonical artifact and manifest integrity now covers volatile/provenance fields, legacy manifests fail closed, and remote generations are retained for race-free replay."
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "In an approved non-D4 maintenance window, run normal activation against the deployment Fabric config and inspect the configured OneLake source root."
    expected: "The activation generation exists under Files/aiops/inventory-source/generations/<run-id> and the source pointer names that generation."
    why_human: "This verification was explicitly local/offline and did not contact OneLake."
  - test: "Confirm from operator/session audit history that the quick-task executor did not invoke Azure/Fabric APIs, Terraform/deployment commands, Job/profile/schedule operations, or stop/interact with D4."
    expected: "No prohibited external or D4 operation occurred."
    why_human: "Git proves file scope but cannot prove the historical absence of external commands."
---

# Quick Task 260910-f2h Verification Report

**Task Goal:** Persist combined activation snapshots in OneLake and add exact generation replay that skips connection validation, discovery, and recombination while preserving Fabric publication, Gold staging, completed marker, shortcuts, and pointer activation.
**Verified:** 2026-09-10T03:58:43Z
**Status:** human_needed
**Re-verification:** Yes — final code-review closure after TDD commits `80bbc4e98` and `89fcb0102`

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Normal activation publishes its combined immutable generation beneath the configured source root, and production uses the exact deployment lakehouse OneLake URI. | ✓ VERIFIED | `publish_combined_snapshot()` ends in `DatasetStore(target_root).publish()` (`src/onboarding/activation.py:369-507`), and normal activation passes `config.source_data_root` (`580-586`). `fabric.config.deploy.yaml:63` names the configured workspace/lakehouse IDs and `Files/aiops/inventory-source`. `DatasetStore` has substantive local/remote generation and pointer implementations (`src/storage/datasets.py:334-704`). Live OneLake access was not attempted and remains a human integration check. |
| 2 | `activate --replay-source-run-id <exact-id>` publishes that generation without connection enumeration, validation, discovery, or recombination. | ✓ VERIFIED | CLI parsing/forwarding is wired in `src/onboarding/cli.py:101-105,286-297`. The replay branch resolves the exact generation before the normal upstream branch (`src/onboarding/activation.py:538-552`). `test_activate_runtime_replays_exact_generation_without_upstream_work` installs fail-on-call doubles for registry enumeration, validation, discovery, and `current_generation`; it passed. |
| 3 | Replay invokes the existing Fabric transaction with the exact generation and activation-owned pointer store, preserving tables, ontology, Gold, completion, shortcuts, and pointer activation. | ✓ VERIFIED | Activation forwards the exact ID and `OneLakeDocumentStore(service.registry.root)` (`src/onboarding/activation.py:593-600`). The sync transaction performs ontology publication, Gold staging/writes, registration/catalog, shortcut finalization, completed-state write, then pointer activation (`src/fabric/sync_service.py:1008-1166`). `test_exact_historical_replay_runs_full_finalization_transaction` passed against the real local service. |
| 4 | Replay never resolves latest/current; an invalid, absent, unreadable, legacy, or modified exact generation fails before Fabric publication and leaves the Exposure Gold pointer untouched. | ✓ VERIFIED | `verify_combined_activation_generation()` resolves only the requested immutable generation, requires the full-integrity contract, and runs both before runtime construction and immediately before sync. Missing/unsafe IDs, legacy manifests, volatile-field tampering, and fail-on-call runtime/pointer doubles passed. Remote publish no longer deletes prior immutable generations. |
| 5 | Normal activation remains result/progress compatible; replay keeps terminal keys and emits only truthful stages. | ✓ VERIFIED | The remediation moved `reporter.start("combined_snapshot")` before `FabricRuntimeConfig.load()` in the normal branch (`src/onboarding/activation.py:580-581`). The named config-failure regression passed and asserts `combined_snapshot/started`, sanitized `combined_snapshot/failed`, and `ActivationFailure.stage == "combined_snapshot"`. Replay config loading remains in the replay-only branch while its event test observes only `activation` and `fabric_publication` starts; source inspection shows no replay call to any validation, discovery, or combined-snapshot reporter path. |
| 6 | `FabricRuntimeConfig.source_data_root` is `Path | str`, resolves local paths relative to config, and preserves OneLake URIs. | ✓ VERIFIED | The type is declared at `src/fabric/config.py:290`; `_resolve_source_root()` (`816-821`) delegates OneLake values to `resolve_root()` while local values use config-relative `_resolve_path()`. Local, OneLake, and deployment-config tests passed. |
| 7 | Exact replay validates status, identity, all combined-snapshot provenance, every declared dataset and ontology artifact, row counts, semantic hashes, full-content hashes, and the overall manifest integrity hash, and rejects any corruption before runtime/publication/pointer construction. | ✓ VERIFIED | `DatasetStore.publish()` writes per-artifact integrity hashes and an overall hash over complete artifact declarations plus all non-derived run metadata. `verify_combined_activation_generation()` requires and recomputes both contracts. The fresh 176-test run covers all reviewed volatile fields, structurally valid metadata changes, legacy manifests, missing files, remote retention, and existing publish/replay behavior. |
| 8 | Work remains local/surgical and isolated from cloud/D4/unrelated dirty files. | ? UNCERTAIN (WARNING) | All twelve implementation/remediation commits touch only scoped source/config/test files. Unrelated `.azure`, Terraform, Fabric Data Agent, Gold-grounding, and other files remain separately dirty and unstaged. This verifier used only local filesystem/Git operations and `UV_OFFLINE=1` tests/lint/compilation and did not interact with D4. Historical executor no-cloud/no-D4 activity still requires operator confirmation. |

**Score:** 7/8 truths verified (0 failed, 1 uncertain process constraint, 0 behavior-unverified)

### Remediation Gap Closure

The prior blocker is closed. Commit `132893d3e` changed the normal branch from:

```python
config = FabricRuntimeConfig.load(fabric_config)
reporter.start("combined_snapshot")
```

to:

```python
reporter.start("combined_snapshot")
config = FabricRuntimeConfig.load(fabric_config)
```

This restores the established failure-stage boundary. The replay branch remains separate: it loads config while `activation` is current and never starts or completes `connection_validation`, `connection_discovery`, or `combined_snapshot`. The two relevant activation tests and the full historical replay transaction test all passed in the verifier's process.

### Replay Integrity Hardening Assessment

Commit `29591f64e` established semantic artifact verification, and commits `7cf710216` and `6c93a8fd1` added structural provenance checks. Final review showed that semantic hashes deliberately exclude fields such as `observed_at`, `ingested_at`, `run_id`, and `lastObservedTimestamp`, and that the old overall hash authenticated only the semantic artifact map. Commits `80bbc4e98` and `89fcb0102` add a separate full-content contract without changing those semantic change-detection semantics.

Every newly published dataset and ontology declaration now carries a canonical SHA-256 `integrityHash` over every field/value. The manifest `integrityHash` covers the complete artifact declaration map and all non-derived run metadata, which includes run/status/query identity, source connection/run provenance, timestamps, subscription scope, and future metadata fields. Canonical JSON is fed incrementally into SHA-256 rather than materialized as one large serialized payload.

Exact activation replay requires this contract, so legacy generations without full-integrity fields fail closed. Verification runs once before runtime construction and again immediately before `FabricSyncService.sync()` starts mapping. In addition, remote DatasetStore publish no longer performs automatic generation deletion; this removes the internal cleanup race for a verified replay path. Local test/development cleanup remains bounded to three generations.

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/storage/datasets.py` | Activation-scoped exact-generation integrity verification and safe retention | ✓ VERIFIED | Publication emits semantic and full-content hashes; replay requires both; remote cleanup is intentionally disabled while local cleanup remains at three generations. |
| `src/onboarding/activation.py` | Durable normal publication and exact replay branch | ✓ VERIFIED | Exact replay verifies before runtime construction and again immediately before sync/mapping. Normal config-load attribution remains unchanged. |
| `src/onboarding/cli.py` | Exact replay parsing and forwarding | ✓ VERIFIED | Parser and conditional forwarding are wired; CLI coverage passed. |
| `src/fabric/config.py` | URI-safe local/OneLake source root | ✓ VERIFIED | `Path | str` implementation is used by activation and runtime construction. |
| `fabric.config.deploy.yaml` | Production combined-snapshot OneLake root | ✓ VERIFIED | Exact workspace/lakehouse URI is configured and parsed without URI mangling. |
| `tests/test_onboarding_activation.py` | Replay skip, forwarding, result/progress, and fail-closed coverage | ✓ VERIFIED | Adds volatile row-field mutations, structurally valid immutable metadata changes, legacy no-integrity refusal, and mutation between first verification and sync. |
| `tests/test_storage.py` | Semantic/full-integrity separation and local retention | ✓ VERIFIED | All four reviewed volatile fields keep semantic hashes stable while changing full-content hashes; POSIX and Windows cleanup remain bounded. |
| `tests/test_onelake_fs.py` | Remote immutable generation retention | ✓ VERIFIED | Five published remote generations remain present and exactly resolvable instead of being trimmed to three. |
| `tests/test_subscription_cli.py` | CLI forwarding/output coverage | ✓ VERIFIED | Exact replay forwarding test passed in the focused suite. |
| `tests/test_fabric_commands.py` | Local/OneLake config resolution coverage | ✓ VERIFIED | Local-path, OneLake URI, and deployment-config tests passed. |
| `tests/test_fabric_sync_service.py` | Historical replay and full finalization coverage | ✓ VERIFIED | Exact historical selection, tables/ontology/Gold, completion, shortcuts, and pointer activation are exercised locally. |

All plan-declared artifacts remain present and substantive. The final closure changes only `src/storage/datasets.py`, `src/onboarding/activation.py`, `tests/test_storage.py`, `tests/test_onelake_fs.py`, and `tests/test_onboarding_activation.py`.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `fabric.config.deploy.yaml` | `src/fabric/config.py` | `source_data_root` load | ✓ WIRED | The deployment URI loads as an unchanged normalized string. |
| `src/onboarding/cli.py` | `src/onboarding/activation.py` | `replay_source_run_id` | ✓ WIRED | The exact supplied value is conditionally forwarded; omission retains normal mode. |
| `src/onboarding/activation.py` | `DatasetStore` | two `verify_combined_activation_generation(exact_generation)` calls | ✓ WIRED | The helper resolves the exact immutable path without consulting `current_generation()`, rejects legacy/tampered content before runtime construction, and rechecks immediately before sync. |
| `src/onboarding/activation.py` | `FabricSyncService.sync` | exact ID plus activation-owned pointer store | ✓ WIRED | Both values cross the boundary together and are asserted by tests. |
| `src/fabric/sync_service.py` | `ExposureGoldFabricPublisher.activate` | existing finalization transaction | ✓ WIRED | Pointer activation follows publication, Gold staging/writes, registration/catalog, shortcuts, and completed-state persistence. |

The PLAN's stale literal `generation_path` pattern does not match the stronger helper call in activation, but manual tracing verifies the intended link through `verify_combined_activation_generation()` and its internal `generation_path()` call.

## Data-Flow Trace

| Flow | Source | Destination | Status |
|---|---|---|---|
| Normal combined snapshot | Validated/discovered connection generations → `publish_combined_snapshot()` → `DatasetStore(config.source_data_root).publish()` | Immutable `generations/<activation-run-id>` and source pointer under the configured local/OneLake root | ✓ FLOWING |
| Exact replay | CLI exact ID → first full verification → runtime construction → second full verification | `FabricSyncService.sync(replay_source_run_id=exact-id)` | ✓ FLOWING |
| Exposure activation | Replayed datasets → normal/ontology/Gold writes → shortcuts → completed state | `ExposureGoldFabricPublisher.activate()` and pointer document | ✓ FLOWING |

### Integrity Matrix

| Integrity property | Enforcement | Test/evidence | Status |
|---|---|---|---|
| Completed status | `manifest["status"] == "completed"` | `incomplete_status` corruption case | ✓ VERIFIED |
| Exact identity | `manifest["runId"] == requested generation` | `wrong_run_id`, traversal, and missing-ID cases | ✓ VERIFIED |
| Source connection provenance | Unique, non-empty list of non-empty strings | Missing, wrong-type, empty, blank, non-string, and duplicate cases | ✓ VERIFIED |
| Source generation provenance | Unique, non-empty list of non-empty strings with cardinality equal to source connections | Missing, wrong-type, empty, blank, non-string, duplicate, and cardinality cases | ✓ VERIFIED |
| Combined-manifest identity | Exact `queryVersion == "combined-subscription-connections-v1"` | Missing, wrong-string, and wrong-type query-version cases | ✓ VERIFIED |
| Declared dataset existence/readability | Required JSONL read for every declaration | Missing and malformed dataset cases | ✓ VERIFIED |
| Dataset row count and semantic hash | Recomputed with publication `_sorted_rows()`/`_semantic_hash()` | Existing count, hash, and non-volatile altered-row cases | ✓ VERIFIED |
| Dataset full-content integrity | Canonical streaming SHA-256 over every persisted row field/value | `observed_at`, `ingested_at`, `run_id`, and `lastObservedTimestamp` mutations | ✓ VERIFIED |
| Ontology integrity | Required JSON object, row count 1, semantic hash, and full-content hash | Presence, missing, non-object, count, and hash cases | ✓ VERIFIED |
| Overall semantic manifest hash | Recomputed from sorted declared semantic artifact hashes | Existing overall-hash corruption case | ✓ VERIFIED |
| Overall full manifest integrity | Complete artifact declarations plus all non-derived immutable run metadata | Valid source ID changes, timestamps, subscription scope, and legacy no-integrity cases | ✓ VERIFIED |
| Retention race safety | Remote cleanup is a documented no-op; local cleanup still keeps three | Five-generation remote and local cleanup tests | ✓ VERIFIED |
| Pre-mapping recheck | Second exact verification after runtime construction and before sync | Build-time volatile-field mutation test | ✓ VERIFIED |
| Fail before runtime/publication/pointer | Verification precedes `build_runtime()` and pointer-store construction | Fail-on-call doubles cover all provenance and integrity corruptions | ✓ VERIFIED |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Complete quick regression set | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_storage.py tests/test_onelake_fs.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py` | 176 tests collected across the six files; all passed; exit 0 | ✓ PASS |
| Provenance and artifact corruption matrix | Included in the complete run: `test_activate_runtime_replay_refuses_corrupt_generation_before_runtime` | All 39 variants passed, including legacy no-integrity input, volatile-only row changes, valid immutable metadata changes, source provenance, artifact, ontology, count, semantic-hash, and overall-integrity cases | ✓ PASS |
| Retention and pre-sync race checks | `test_remote_dataset_store_retains_all_immutable_generations`, both local cleanup tests, and `test_activate_runtime_reverifies_exact_generation_before_sync` | Remote retained five exact generations, local retained three, and mutation during runtime construction failed before sync | ✓ PASS |
| Exact no-latest/no-upstream replay | Included in the complete run: `test_activate_runtime_replays_exact_generation_without_upstream_work` and `test_missing_exact_replay_does_not_fallback_or_activate_pointer` | Both passed; fail-on-call doubles reject registry enumeration, validation, discovery, and `current_generation`; exact missing ID leaves pointer empty | ✓ PASS |
| Full replay transaction | Included in the complete run: `test_exact_historical_replay_runs_full_finalization_transaction`, `test_successful_publication_hooks_follow_exact_side_effect_order`, and pre-activation failpoint matrix | Historical generation selected while a different generation is current; normal/ontology/Gold writes, registration/catalog, shortcuts, completed state, and final pointer activation passed | ✓ PASS |
| Scoped code quality | `UV_OFFLINE=1 uv run ruff check ...` | `All checks passed!` | ✓ PASS |
| Python compilation | `UV_OFFLINE=1 uv run python -m compileall -q ...` | No output; exit 0 | ✓ PASS |
| Committed task diff integrity | `git diff --check 80bbc4e98^..89fcb0102`, twelve-commit path inspection, and `git status --short` | No whitespace errors or staged files; final review commits contain only scoped source/test paths; unrelated pre-existing dirty files remain separate | ✓ PASS |

## Probe Execution

No task probe was declared in the plan/summary and no applicable quick-task probe was found.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| `QUICK-260910-F2H` | `PLAN.md` | Durable combined snapshots and exact activation replay | ? HUMAN | All locally verifiable implementation and behavior requirements pass. Production OneLake integration and historical no-cloud/no-D4 confirmation remain human-only. The ID is not separately registered in `.planning/REQUIREMENTS.md` or `ROADMAP.md`. |

## Anti-Patterns Found

No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, placeholder, empty-handler blocker, missing artifact, or hollow implementation was found in the scoped files. The `None`/empty initializers found by the stub scan are typed runtime state or test fixtures, not shipped UI/data stubs.

### Adversarial Disconfirmation Notes

- **Partially automatable requirement:** production OneLake reachability and write authorization cannot be established offline. URI parsing, routing, and local storage behavior pass, but the live integration remains a human check.
- **Test-boundary caveat:** the exact historical replay test proves historical selection and required outcomes, while the separate shared-transaction ordering test proves the complete side-effect order. No single test covers both dimensions; together they exercise the same `FabricSyncService.sync()` path.
- **Uncovered external error path:** a real OneLake credential/network failure was intentionally not induced. Local missing, malformed, unreadable, and corrupt-generation failures are covered and fail before runtime/pointer construction.

## Human Verification Required

### 1. Production OneLake integration

**Test:** In an approved non-D4 maintenance window, run normal activation against the deployment Fabric config and inspect the configured source root.

**Expected:** The generation is present under `Files/aiops/inventory-source/generations/<run-id>` and the source pointer names it.

**Why human:** The requested verification was local/offline and explicitly prohibited cloud/network operations.

### 2. Historical cloud/D4 non-interaction

**Test:** Confirm from operator or session audit history that the quick-task executor did not invoke Azure/Fabric APIs, Terraform/deployment commands, Job/profile/schedule operations, or stop/interact with D4.

**Expected:** No prohibited external or D4 operation occurred.

**Why human:** Git proves surgical file scope but cannot prove the historical absence of external commands.

## Gaps Summary

No implementation or automated-verification gap remains. Combined replay now rejects legacy manifests, every requested invalid provenance shape, structurally valid metadata tampering, and semantic-exclusion field changes. The second verification and durable remote retention remove the identified internal publish/replay race. Normal activation compatibility, truthful replay progress, exact historical selection, and the full Fabric/Gold/completed-marker/shortcut/pointer transaction remain green in the 176-test quick suite.

The report remains `human_needed` only for the explicitly prohibited live OneLake integration check and historical operator confirmation that no cloud/D4 operation occurred.

---

_Verified: 2026-09-10T03:58:43Z_
_Verifier: the agent (gsd-verifier)_
