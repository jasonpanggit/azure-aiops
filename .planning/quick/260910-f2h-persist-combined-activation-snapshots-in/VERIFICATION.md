---
phase: quick-260910-f2h
verified: 2026-09-10T03:40:36Z
status: human_needed
score: 7/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/8
  gaps_closed:
    - "Combined activation replay now requires the exact queryVersion, unique non-empty sourceRunIds and sourceConnectionIds, and matching source-list cardinality before runtime or pointer construction."
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
**Verified:** 2026-09-10T03:40:36Z
**Status:** human_needed
**Re-verification:** Yes — final provenance-gap closure after commits `7cf710216` and `6c93a8fd1`

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Normal activation publishes its combined immutable generation beneath the configured source root, and production uses the exact deployment lakehouse OneLake URI. | ✓ VERIFIED | `publish_combined_snapshot()` ends in `DatasetStore(target_root).publish()` (`src/onboarding/activation.py:369-507`), and normal activation passes `config.source_data_root` (`580-586`). `fabric.config.deploy.yaml:63` names the configured workspace/lakehouse IDs and `Files/aiops/inventory-source`. `DatasetStore` has substantive local/remote generation and pointer implementations (`src/storage/datasets.py:334-704`). Live OneLake access was not attempted and remains a human integration check. |
| 2 | `activate --replay-source-run-id <exact-id>` publishes that generation without connection enumeration, validation, discovery, or recombination. | ✓ VERIFIED | CLI parsing/forwarding is wired in `src/onboarding/cli.py:101-105,286-297`. The replay branch resolves the exact generation before the normal upstream branch (`src/onboarding/activation.py:538-552`). `test_activate_runtime_replays_exact_generation_without_upstream_work` installs fail-on-call doubles for registry enumeration, validation, discovery, and `current_generation`; it passed. |
| 3 | Replay invokes the existing Fabric transaction with the exact generation and activation-owned pointer store, preserving tables, ontology, Gold, completion, shortcuts, and pointer activation. | ✓ VERIFIED | Activation forwards the exact ID and `OneLakeDocumentStore(service.registry.root)` (`src/onboarding/activation.py:593-600`). The sync transaction performs ontology publication, Gold staging/writes, registration/catalog, shortcut finalization, completed-state write, then pointer activation (`src/fabric/sync_service.py:1008-1166`). `test_exact_historical_replay_runs_full_finalization_transaction` passed against the real local service. |
| 4 | Replay never resolves latest/current; an invalid, absent, or unreadable exact generation fails before Fabric publication and leaves the Exposure Gold pointer untouched. | ✓ VERIFIED | `verify_combined_activation_generation()` resolves only the requested immutable generation and now rejects every tested query-version and source-provenance corruption before `build_runtime` or pointer-store construction. Missing/unsafe exact-ID tests and fail-on-call doubles also passed. |
| 5 | Normal activation remains result/progress compatible; replay keeps terminal keys and emits only truthful stages. | ✓ VERIFIED | The remediation moved `reporter.start("combined_snapshot")` before `FabricRuntimeConfig.load()` in the normal branch (`src/onboarding/activation.py:580-581`). The named config-failure regression passed and asserts `combined_snapshot/started`, sanitized `combined_snapshot/failed`, and `ActivationFailure.stage == "combined_snapshot"`. Replay config loading remains in the replay-only branch while its event test observes only `activation` and `fabric_publication` starts; source inspection shows no replay call to any validation, discovery, or combined-snapshot reporter path. |
| 6 | `FabricRuntimeConfig.source_data_root` is `Path | str`, resolves local paths relative to config, and preserves OneLake URIs. | ✓ VERIFIED | The type is declared at `src/fabric/config.py:290`; `_resolve_source_root()` (`816-821`) delegates OneLake values to `resolve_root()` while local values use config-relative `_resolve_path()`. Local, OneLake, and deployment-config tests passed. |
| 7 | Exact replay validates status, identity, all combined-snapshot provenance, every declared dataset and ontology artifact, row counts, semantic hashes, and the overall manifest hash, and rejects any corruption before runtime/publication/pointer construction. | ✓ VERIFIED | The activation-scoped verifier requires `queryVersion == "combined-subscription-connections-v1"`, unique non-empty string lists for both provenance fields, equal list cardinality, and the existing artifact/hash chain. The 30-case focused matrix passed with runtime and pointer constructors set to fail on call. |
| 8 | Work remains local/surgical and isolated from cloud/D4/unrelated dirty files. | ? UNCERTAIN (WARNING) | All ten implementation/remediation commits touch only scoped source/config/test files. Unrelated `.azure`, Terraform, Fabric Data Agent, Gold-grounding, and other files remain separately dirty and unstaged. This closure used only local filesystem/Git operations and offline tests/lint and did not interact with D4. Historical no-cloud/no-D4 activity remains an operator confirmation. |

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

Commit `29591f64e` established artifact-integrity verification. Commits `7cf710216` and `6c93a8fd1` close the remaining provenance gap. The verifier is now deliberately named `verify_combined_activation_generation()` so unrelated `DatasetStore` generations do not inherit activation-only metadata requirements. It requires the exact combined query version, validates both source lists as non-empty lists of non-empty strings, rejects duplicates in either list, and requires one durable source run per selected connection.

These checks run immediately after exact immutable generation resolution and before dataset reads, runtime construction, Fabric publication, or pointer-store construction. The shared query-version constant is used by both combined publication and replay verification, preventing writer/verifier literal drift.

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/storage/datasets.py` | Activation-scoped exact-generation integrity verification | ✓ VERIFIED | `verify_combined_activation_generation()` enforces the full combined provenance contract and existing artifact/hash integrity without imposing those metadata requirements on generic DatasetStore publication. |
| `src/onboarding/activation.py` | Durable normal publication and exact replay branch | ✓ VERIFIED | Exists, substantive, and wired. Normal config-load attribution is restored without moving replay into the combined-snapshot stage. |
| `src/onboarding/cli.py` | Exact replay parsing and forwarding | ✓ VERIFIED | Parser and conditional forwarding are wired; CLI coverage passed. |
| `src/fabric/config.py` | URI-safe local/OneLake source root | ✓ VERIFIED | `Path | str` implementation is used by activation and runtime construction. |
| `fabric.config.deploy.yaml` | Production combined-snapshot OneLake root | ✓ VERIFIED | Exact workspace/lakehouse URI is configured and parsed without URI mangling. |
| `tests/test_onboarding_activation.py` | Replay skip, forwarding, result/progress, and fail-closed coverage | ✓ VERIFIED | Covers valid multi-connection provenance plus missing, wrong-type, empty, blank, non-string, duplicate, mismatched-cardinality, and wrong query-version corruption with fail-on-call runtime/pointer doubles. |
| `tests/test_subscription_cli.py` | CLI forwarding/output coverage | ✓ VERIFIED | Exact replay forwarding test passed in the focused suite. |
| `tests/test_fabric_commands.py` | Local/OneLake config resolution coverage | ✓ VERIFIED | Local-path, OneLake URI, and deployment-config tests passed. |
| `tests/test_fabric_sync_service.py` | Historical replay and full finalization coverage | ✓ VERIFIED | Exact historical selection, tables/ontology/Gold, completion, shortcuts, and pointer activation are exercised locally. |

All plan-declared artifacts remain present and substantive. The final closure changes only `src/storage/datasets.py`, `src/onboarding/activation.py`, and `tests/test_onboarding_activation.py`.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `fabric.config.deploy.yaml` | `src/fabric/config.py` | `source_data_root` load | ✓ WIRED | The deployment URI loads as an unchanged normalized string. |
| `src/onboarding/cli.py` | `src/onboarding/activation.py` | `replay_source_run_id` | ✓ WIRED | The exact supplied value is conditionally forwarded; omission retains normal mode. |
| `src/onboarding/activation.py` | `DatasetStore` | `verify_combined_activation_generation(exact_generation)` | ✓ WIRED | The activation-scoped helper resolves the exact immutable path without consulting `current_generation()` and validates provenance before returning the trusted manifest. |
| `src/onboarding/activation.py` | `FabricSyncService.sync` | exact ID plus activation-owned pointer store | ✓ WIRED | Both values cross the boundary together and are asserted by tests. |
| `src/fabric/sync_service.py` | `ExposureGoldFabricPublisher.activate` | existing finalization transaction | ✓ WIRED | Pointer activation follows publication, Gold staging/writes, registration/catalog, shortcuts, and completed-state persistence. |

The PLAN's stale literal `generation_path` pattern does not match the stronger helper call in activation, but manual tracing verifies the intended link through `verify_combined_activation_generation()` and its internal `generation_path()` call.

## Data-Flow Trace

| Flow | Source | Destination | Status |
|---|---|---|---|
| Normal combined snapshot | Validated/discovered connection generations → `publish_combined_snapshot()` → `DatasetStore(config.source_data_root).publish()` | Immutable `generations/<activation-run-id>` and source pointer under the configured local/OneLake root | ✓ FLOWING |
| Exact replay | CLI exact ID → `DatasetStore.verify_combined_activation_generation()` → verified provenance/manifest/artifacts | `FabricSyncService.sync(replay_source_run_id=exact-id)` | ✓ FLOWING |
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
| Dataset row count and semantic hash | Recomputed with publication `_sorted_rows()`/`_semantic_hash()` | Count, hash, and altered-row cases | ✓ VERIFIED |
| Ontology integrity | Required JSON object, row count 1, semantic hash | Missing, non-object, count, and hash cases | ✓ VERIFIED |
| Overall manifest hash | Recomputed from sorted declared artifact hashes | Overall-hash corruption case | ✓ VERIFIED |
| Fail before runtime/publication/pointer | Verification precedes `build_runtime()` and pointer-store construction | Fail-on-call doubles cover all provenance and integrity corruptions | ✓ VERIFIED |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused provenance matrix | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_onboarding_activation.py -k 'replays_exact_generation_without_upstream_work or replay_refuses_corrupt_generation_before_runtime'` | 30 tests passed; exit 0 | ✓ PASS |
| Complete quick regression set | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_storage.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py` | 142 tests passed; exit 0 | ✓ PASS |
| Scoped code quality | `UV_OFFLINE=1 uv run ruff check ...` | `All checks passed!` | ✓ PASS |
| Python compilation | `UV_OFFLINE=1 uv run python -m compileall -q ...` | No output; exit 0 | ✓ PASS |
| Adversarial combined provenance | Parameterized missing/wrong-type/empty/blank/non-string/duplicate/cardinality/query-version corruptions with fail-on-call runtime and pointer doubles | Every corruption raised `ActivationFailure` during `activation`; exit 0 | ✓ PASS |
| Committed task diff integrity | `git diff --check` and scoped commit inspection | No whitespace errors; closure commits touched only scoped files | ✓ PASS |

## Probe Execution

No task probe was declared in the plan/summary and no applicable quick-task probe was found.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| `QUICK-260910-F2H` | `PLAN.md` | Durable combined snapshots and exact activation replay | ? HUMAN | All locally verifiable implementation and behavior requirements pass. Production OneLake integration and historical no-cloud/no-D4 confirmation remain human-only. The ID is not separately registered in `.planning/REQUIREMENTS.md` or `ROADMAP.md`. |

## Anti-Patterns Found

No `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, placeholder, empty-handler blocker, missing artifact, or hollow implementation was found in the scoped files.

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

No implementation or automated-verification gap remains. Combined replay now rejects every requested invalid provenance shape before runtime, publication, or pointer construction, while the successful two-connection fixture proves valid one-run-per-connection provenance is accepted. Normal activation compatibility, truthful replay progress, exact historical selection, and the full Fabric/Gold/completed-marker/shortcut/pointer transaction remain green in the 142-test quick suite.

The report remains `human_needed` only for the explicitly prohibited live OneLake integration check and historical operator confirmation that no cloud/D4 operation occurred.

---

_Verified: 2026-09-10T03:40:36Z_
_Verifier: the agent (gsd-verifier)_
