---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 19
status: cloud-blocked
checkpoint: local-complete
updated: 2026-09-07T15:14:35Z
---

# Phase 13 Plan 19 Local Completion Checkpoint

Local implementation is complete and committed. Cloud completion is frozen
until the concurrent Exposure deployment has been reconciled.

## Locally Complete

- Production API/coordinator/publisher capability roots and dispatch-only
  publisher store construction are implemented and structurally tested.
- Command, state, dispatch, publication, and validation registry roots and
  Fabric role boundaries are declared.
- Prepare and cleanup Jobs have fixed commands, arguments, environment,
  identity, retry, timeout, parallelism, and completion templates.
- Fixture lifecycle preparation, cleanup, expiry sweep, ownership, fencing,
  retained receipts, and exactly-three-record limits are covered by tests.
- Coordinator validation classification selects the isolated validation
  ConnectionRegistry without changing selection or reauthorization logic.
- Coordinator injection metadata is Terraform-owned and no runtime Job-start
  role assignment is declared.
- Saved-plan validation uses an exact address allowlist, rejects
  destroy/replace/unlisted changes, and verifies digest-pinned images and
  complete template hashes.
- Deployment evidence is closed and hash-only. The previous live snapshot is
  explicitly marked `superseded`; `--require-applied` now fails closed until
  fresh evidence is collected.

## Local Verification

- `uv run pytest -q tests/test_ontology_deployment_plan.py tests/test_ontology_discovery_job_infra.py tests/test_ontology_discovery_runtime.py tests/test_ontology_publisher_identity.py -x`
- `terraform -chdir=infra/terraform fmt -check`
- `terraform -chdir=infra/terraform validate`
- Changed-file Ruff validation
- `uv run python .planning/scripts/preflight_phase_13.py`

## Cloud Checkpoint Remaining

After Exposure explicitly releases the deployment lane:

1. Confirm shared main is clean and no Terraform apply is active.
2. Reconcile the final Plan 19 branch with the completed Exposure source.
3. Build fresh immutable API/web images from that exact reconciled source.
4. Regenerate production and validation saved plans from canonical state.
5. Re-run the exact allowlist validator and require zero destroy/replace.
6. Apply only the reviewed validation saved plan.
7. Without starting fixture Jobs, re-read app/Job templates and effective
   runtime/deployer role definitions.
8. Regenerate `.planning/eval/ontology-gap-deployment.json` with
   `status: applied`, then run the `--require-applied` gate.
9. Only then create `13-19-SUMMARY.md`, check off Roadmap Plan 19, and remove
   the Phase 13 Plan 19 blocker without changing Phase 03.1 active fields.

No Plan 20 work has started.
