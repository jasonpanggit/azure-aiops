# Ontology discovery shadow operations

Phase 13 operates only in **shadow mode**. Model-derived relationships may be
reviewed and measured, but they must remain absent from authoritative
candidates, immutable stages, the active generation, exports, and all
consumers. There is no release, canary, allowlist, or activation option in the
live validator.

## Credentialed validation

### Prerequisites

- Azure CLI is authenticated to the deployment subscription.
- The selected runtime is `prompt-agent`. Stop and replan if the approved
  selection is `hosted-agent-exception`.
- `AIOPS_FABRIC_CONFIG` identifies connection metadata, but its ordinary
  `fabric.workspace_id` and `fabric.lakehouse_id` are production resources and
  are never used as Phase 13 state defaults.
- Phase 13 state and RBAC-validation workspace/lakehouse IDs are supplied
  explicitly or resolved from canonical Terraform outputs.
- `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_ONTOLOGY_AGENT_NAME` identify the
  deployed proposal-only curator.

Set the non-secret target values in the operator environment:

```bash
export AIOPS_FABRIC_CONFIG=/secure/path/fabric.config.deploy.yaml
export AIOPS_AZURE_SUBSCRIPTION_ID=<subscription-guid>
export AIOPS_ONTOLOGY_RESOURCE_GROUP=<resource-group>
export AIOPS_ONTOLOGY_JOB_NAME=<scheduled-job-name>
export AIOPS_ONTOLOGY_STATE_WORKSPACE_ID=<phase13-state-workspace-guid>
export AIOPS_ONTOLOGY_STATE_LAKEHOUSE_ID=<phase13-state-lakehouse-guid>
export AIOPS_ONTOLOGY_RBAC_WORKSPACE_ID=<rbac-workspace-guid>
export AIOPS_ONTOLOGY_RBAC_LAKEHOUSE_ID=<rbac-lakehouse-guid>
export AIOPS_ONTOLOGY_RUNTIME_SELECTION=prompt-agent
export FOUNDRY_PROJECT_ENDPOINT=<project-endpoint>
export FOUNDRY_ONTOLOGY_AGENT_NAME=<curator-agent-name>
```

Run the release-closing shadow gate:

```bash
uv run python scripts/validate_ontology_discovery_live.py \
  --shadow \
  --assert-authoritative-model-edge-count-zero \
  --assert-release-status blocked-or-pending \
  --fail-on-threshold \
  --fail-on-missing-evidence
```

The command:

1. validates Azure subscription context and the exact Phase 13 state and RBAC
   Fabric resources;
2. reads the deployed Foundry curator and checks prompt kind, active state,
   `gpt-5.4-mini`, and the exact four read-only tools;
3. captures at least two successful scheduled no-click executions, then starts
   and waits for two finite non-production executions to prove run-now and
   restart behavior;
4. executes duplicate-suppression, restart, 50/200/40 batching,
   8,000/1,200-token, 60-second timeout, injection, scope, identity,
   publication, stale-writer, consumer, rollback, API, and durable-evaluation
   contracts;
5. reruns Promptfoo with `--no-cache`, launches and terminates loopback Phoenix
   for redaction inspection, runs the `/connections` Ontology automation UI
   tests, and emits every sanitized alert-smoke rule;
6. persists a content-addressed `EvaluationSnapshot` and a per-pair readiness
   record in the isolated Phase 13 state lakehouse, then reconstructs fresh and
   stale outcomes from that durable store; and
7. writes `.planning/eval/ontology-discovery-shadow-YYYY-MM-DD.json`.

No API or web application is built, pushed, restarted, or deployed by this
command. The only cloud mutations are bounded manual starts of the existing
non-production coordinator Job and writes beneath the isolated Phase 13
evaluation state prefix.

## Reading the report

A successful validator execution has:

- top-level `status: PASS`;
- `release_status: BLOCKED/PENDING`;
- an empty `missing_evidence` list;
- `authoritative_model_edge_count: 0`;
- zero counts at `candidate`, `stage`, `active`, and `consumer`;
- schedule `run_now`, `restart`, and `duplicate_suppression` all `PASS`;
- deterministic `generation-old → generation-new → generation-old` evidence
  with API, Fabric, agent, export, and semantic consumers all `PASS`;
- durable evaluation `fresh` and `stale` checks both `PASS`;
- Promptfoo, Phoenix, alert, API audit, and UI audit checks all `PASS`; and
- one record for every allowed subject/predicate/object type pair.

Deployment identifiers are replaced with short SHA-256 references. Prompts,
evidence bodies, resource IDs, scope values, credentials, tokens, principal
IDs, raw errors, and response bodies are excluded.

`PASS` means the shadow safety gate is complete. It does **not** mean that a
model pair is eligible. Every pair remains `BLOCKED/PENDING` and records:

- observed consecutive shadow days;
- expert-adjudicated eligible proposal count;
- critical failure codes;
- observed/required pair metric fields;
- approvals; and
- the explicit missing predicates
  `30_consecutive_shadow_days` and
  `200_expert_adjudicated_eligible_proposals`.

An unavailable metric is stored as `null`, never as a synthetic passing value.

## Durable evidence and retention

The validator writes only under the non-production Phase 13 state root:

```text
Files/aiops/ontology_evaluations/
├── snapshots/<scope-hash>/<snapshot-id>.json
├── history/<scope-hash>.json
├── latest/<scope-hash>.json
└── pair-readiness/YYYY-MM-DD-shadow.json
```

Snapshots are immutable and content-addressed. Latest/history and daily pair
records use revision checks. Preserve these records for the whole observation
window. Do not copy them to the production workspace or treat local test
fixtures as expert labels.

If the command exits nonzero, inspect only `missing_evidence` and the sanitized
`blocker`. Repair or re-run the missing evidence source. Never edit a report to
turn a failure into a pass.

## Emergency disable

If any scope disclosure, unauthorized mutation, successful injection,
model-derived authoritative edge, stale-writer promotion, partial generation,
missing audit, or unrollbackable pointer is observed:

1. stop new scheduled executions by disabling the existing ontology discovery
   Job schedule through the approved infrastructure change process;
2. do not grant the API, coordinator, or curator a Fabric writer role;
3. preserve the active pointer, immutable stages, run records, evaluation
   snapshots, alert correlation hashes, and sanitized report;
4. if a deterministic publication is implicated, use the publisher-owned
   rollback procedure below; and
5. keep release status `BLOCKED/PENDING` and open an incident before resuming
   the schedule.

Do not delete immutable generations or evaluation evidence during containment.

## Deterministic rollback

Rollback remains publisher-owned and ETag/fence protected:

1. read the current generation projection and capture its active generation,
   retained prior generation, source generation, pointer ETag, and validation
   state;
2. confirm the target generation is complete, deterministic-only, validated,
   audited, and compatible with API, Fabric, agent, export, and semantic
   consumers;
3. request rollback through the narrow operations API/UI using the observed
   pointer ETag and an operator reason;
4. verify the publisher wrote immutable rollback intent/result receipts and
   advanced the pointer with a newer fence;
5. verify every consumer resolves the target generation; and
6. rerun the shadow validator. The expected visibility sequence is
   old/new/old and the model-derived edge count remains zero throughout.

The API identity cannot stage or move the pointer. It delegates only the
reviewed rollback request to the publisher boundary.

## Later model-admission review

Phase 13 cannot activate model-derived admission. A future change must begin
with a new reviewed plan and a blocking human decision checkpoint. For each
pair independently, that plan must reconstruct durable evidence showing all
of the following:

- at least 30 consecutive shadow days with reset evidence for any critical
  failure;
- at least 200 expert-adjudicated eligible proposals;
- no critical failures;
- escalation recall 1.00, recall at least 0.90, and Wilson precision lower
  bound at least 0.98;
- all AI-SPEC quality, freshness, audit, latency, token, and batching gates;
- ontology steward, security owner, and Fabric governance steward approvals;
- a reversible pair-scoped rollout design and tested immediate revocation; and
- deterministic edges winning every collision.

Until that new plan is reviewed and implemented, no CLI flag, UI action,
review decision, configuration field, or synthetic test result can enable a
pair.

## OneLake data-access role reconciliation

The five `Phase13EvidenceRead` OneLake data-access roles for the evidence
identity are managed outside Terraform due to the Fabric provider 1.13
ManagedIdentity round-tripping bug. See
[docs/onelake-data-access-role-migration.md](onelake-data-access-role-migration.md)
for the full migration procedure.

Create the mode-0600 contract from the sensitive Terraform output:

```bash
contract_file="$(mktemp)"
chmod 0600 "$contract_file"
terraform -chdir=infra/terraform output -json \
  ontology_evidence_role_contract >"$contract_file"
source_contract_file="$(mktemp)"
chmod 0600 "$source_contract_file"
terraform -chdir=infra/terraform output -json \
  ontology_coordinator_source_role_contract >"$source_contract_file"
```

Run a local dry run first, then the server-side dry-run, ETag-guarded write, and
post-write verification:

```bash
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --contract-file "$contract_file" \
  --coordinator-source-contract-file "$source_contract_file" \
  --azure-config-dir "$AIOPS_DEPLOYER_AZURE_CONFIG_DIR" \
  --output .planning/eval/ontology-onelake-role-dry-run.json
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --contract-file "$contract_file" \
  --coordinator-source-contract-file "$source_contract_file" \
  --azure-config-dir "$AIOPS_DEPLOYER_AZURE_CONFIG_DIR" \
  --output .planning/eval/ontology-onelake-role-reconciliation.json \
  --apply
rm "$contract_file"
rm "$source_contract_file"
```

The script acquires a delegated Fabric token from only the selected mode-0700
Azure CLI context. Each write is preceded by Fabric's `dryRun=true` request,
uses the same collection ETag, and is followed by a GET that must return the
exact `ManagedIdentity` member shape. Unrelated roles are preserved.

The fixed prepare Job reads the production connection registry through the
separate `Phase13CoordinatorConnectionRead` role and mirrors exactly one
eligible non-production connection into the isolated validation registry.
Only its credential reference is copied; secrets remain in Key Vault and are
resolved at runtime by the coordinator identity. The other two fixture members
remain synthetic to exercise bounded retry and fairness behavior. In
validation, both coordinator and publisher Jobs are manual-only so scheduled
executions cannot race the evidence sequence.
# Bounded semantic evolution

Semantic evolution is an advisory, proposal-only extension of ontology
discovery. It is disabled by default (`fabric.ops_semantic_evolution.enabled:
false`). Profiles and evidence are pinned to one immutable source generation.
Only additive descriptions, synonyms/classifications, columns, relationships,
hierarchies, and measures may be proposed; identity, cardinality, destructive
changes, and scope widening are rejected.

Reviewed proposals are stored through `OntologyRunStore` and only accepted
proposals are compiled into a deterministic local candidate definition. The
pipeline writes `semantic-candidate.json`, `semantic-profile.json`, and
`semantic-monitoring.json` atomically to the configured local artifact root.
It never acquires tokens, mutates Fabric, or publishes a semantic model.

The optional Gold grounding adapter is fail-closed and generation-pinned. Its
default allowlist is `gold_exposure_facts`,
`gold_container_exposure_current`, `gold_container_exposure_coverage`,
`ontology_entities`, `ontology_relationships`, `ontology_health`,
`ontology_business_context`, and `ontology_compliance_context`. Sync invokes
the advisory callback only after immutable publication finalization; callback
failures are logged and do not fail publication.
