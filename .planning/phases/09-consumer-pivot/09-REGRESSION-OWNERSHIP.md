# Phase 9 Full-Suite Regression Ownership

**Investigation date:** 2026-08-28  
**Phase boundary:** `1b730f77` (`test(09-01): cover policy-grounded contextual findings`) is the
last pre-Phase-9 commit; Phase 9 implementation commits are `951f7c29` through `8b0d7a35`.

## Result

All three failures reproduce at the Phase 9 boundary. They are therefore pre-existing
baseline failures, not consumer-pivot regressions. No unrelated governance, ontology, or
storage behavior was changed to make the Phase 9 gate appear green.

| Failure | Reproduction and exact result | Owning change/file | Causal classification | Required fix owner and regression policy |
|---|---|---|---|---|
| `TestGovernancePipelineComparison::test_spn_governance_matches_aiops` | `uv run python -m pytest tests/test_governance_pipeline.py::TestGovernancePipelineComparison::test_spn_governance_matches_aiops -q` fails because the statuses are `{'expired', 'healthy'}` and do not contain `expiring_soon`. The same assertion fails at `1b730f77`. The fixture says `expires_at=2026-08-15` while `test_now=2026-08-27`, so the credential is already expired, not expiring in about 19 days. | Test/fixture introduced by `b9be38ed` (`tests/test_governance_pipeline.py`); expiry classification implementation is from pre-Phase-9 `a40d47cf` (`src/intelligence/governance/identity.py`, now imported through `intelligence.governance`). The Phase 9 Fabric pipeline only consumes that engine and was not changed by Phase 9. | **Pre-existing test-fixture/expectation mismatch.** | Governance owner should either move the fixture expiry to a future date or assert `expired`, then retain the isolated comparison test and full-suite gate. Do not change Phase 9 governance code. |
| `test_situations_are_registered_as_ontology_entities_with_typed_links` | `uv run python -m pytest tests/test_situations_ontology.py::test_situations_are_registered_as_ontology_entities_with_typed_links -q` fails because an entity with `entity_type == "Situation"` exists but no mapped relationship has `subject_type == "Situation"`. The same assertion fails at `1b730f77`. | Assertion introduced by `1d31e57c` (`tests/test_situations_ontology.py`); situation materialization/link behavior is pre-Phase-9 (`0ed80fd`, `src/situations/materializer.py`) and ontology mapping is pre-Phase-9 (`34915d03`/`a40d47cf`, `src/fabric/dataset_mapper.py`). Phase 9 did not modify these files. | **Pre-existing ontology contract mismatch.** | Situation/ontology owner should align the expected typed-link projection with the materializer and mapper contract (or add the missing link in that domain), retaining this focused test and the full-suite gate. Do not broaden INV-09/INV-10 to repair it here. |
| `test_partial_publish_preserves_hash_baseline_for_next_full_publish` | `uv run python -m pytest tests/test_storage.py::test_partial_publish_preserves_hash_baseline_for_next_full_publish -q` fails because the second full publish reports `changedDatasets=[]`, while the first reports 38 changed datasets. The same assertion fails at `1b730f77`. | Test originates in pre-Phase-9 `34915d03` (`tests/test_storage.py`); neutral publish/hash behavior is pre-Phase-9 `aa9ffb0` (`src/storage/datasets.py`) with compatibility changes in `a40d47cf`. Phase 9 did not modify the storage files or test. | **Pre-existing storage baseline/hash contract failure.** | Storage owner should preserve the hash baseline across a partial publication, then keep this focused test and full-suite gate as the regression detector. No Phase 9 storage fix is justified. |

## Boundary Evidence

The relevant file diff from the Phase 9 boundary to the current Phase 9 tip is limited to
the inventory consumer migration files:

```text
M src/onboarding/agent_queries.py
M src/onboarding/inventory_read_adapter.py
```

There are no Phase 9 changes to the failing tests, governance engine/pipeline, situation
materializer/mapper/store, or dataset storage implementation. Running the three tests from
the detached `1b730f77` baseline produced the same three failures, independently of the
current working-tree changes.

## Verification Policy

The failures remain visible rather than being skipped, xfailed, or weakened:

1. Run each isolated command above when investigating ownership.
2. Run the complete Phase 9 focused backend suite separately; it must remain green.
3. Run `uv run python -m pytest -q`; residual failures must match the three named baseline
   failures until their owning domains repair them.
4. Any future change to these areas must rerun its isolated test and compare the failure
   set against this record before being attributed to Phase 9.

**Residual status:** three pre-existing failures remain in the full backend suite; zero
Phase 9-caused failures were found.
