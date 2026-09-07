# Ontology discovery shadow operations

Phase 13 operates only in **shadow mode**. Model-derived relationships may be
reviewed and measured, but they must remain absent from authoritative
candidates, immutable stages, the active generation, exports, and all
consumers. There is no release, canary, allowlist, or activation option in the
live validator.

## Plan 20 fixed-template deployed lifecycle

Plan 20 is a separate, fail-closed validation procedure. It does not use the
legacy ambient-credential shadow command described later in this document.
It runs only in the `validation` environment and preserves every ontology pair
at `BLOCKED/PENDING`.

### Credential boundary

Create or obtain two independently authenticated Azure CLI homes:

- `AIOPS_DEPLOYER_AZURE_CONFIG_DIR`: the deployment principal. This identity
  may read and start only the five deployed ontology Jobs.
- `AIOPS_EVIDENCE_AZURE_CONFIG_DIR`: a genuinely read-only evidence identity.
  It may read ARG, Fabric, and OneLake evidence, but it has no Container Apps
  Job read/start/stop action and no data-plane mutation action.

Both directories must already exist with mode `0700`. Authenticate each
identity with `AZURE_CONFIG_DIR` set to its own directory. Never copy an
`azureProfile.json`, token cache, or complete deployer directory to create the
evidence context. The validator removes ambient `AZURE_*` and `ARM_*`
credential variables from every child process and records only identity and
action-set hashes.

Before any Job execution, verify no Terraform plan/apply process owns the
deployment lane. Terraform language servers and read-only MCP servers do not
own that lane; `terraform plan`, `terraform apply`, and wrapper processes that
can apply state do. Do not build, push, apply, restart apps, or alter saved Job
templates while Exposure owns the lane.

### Secure target derivation

Resolve API/web URLs, resource group, Foundry endpoint/name, and state and
validation Fabric IDs from canonical Terraform outputs or the already
deployed Job templates. Resolve the subscription from the isolated deployer
context, use connection `demo`, and obtain API credentials through the
approved secret channel. Keep tokens in process memory only. Do not print,
persist, hash together with public fields, or pass tokens on a command line.

The deployment evidence gate is:

```bash
uv run python scripts/validate_ontology_deployment_plan.py \
  --evidence .planning/eval/ontology-gap-deployment.json \
  --require-applied \
  --assert-fixed-fixture-job-templates \
  --assert-no-runtime-job-start-grants \
  --assert-validation-connection-root \
  --assert-coordinator-injection-tag
```

The applied API/Job digest is
`sha256:8c2ff509670daf392f1eae8f7b0105f9469243bd704c1a38bb5bf70b114e8ecd`
and the applied web digest is
`sha256:bde3d582c0d96ee3f69ab89690cf5ba8a2d498e1a6fc4a567e09a95063eca84f`.
The validator compares saved-template hashes against the applied Plan 19
evidence before and after every execution.

### Exact lifecycle order

1. **Preflight.** Prove distinct identity hashes, mode-`0700` homes, no
   credential bleed, deployer-only Job control, evidence-only ARG/Fabric/
   OneLake reads, no runtime Job-start grant, exact validation root, and all
   five unchanged saved-template hashes.
2. **Prepare.** Start `ontology-fixture-prepare` with the saved template. The
   `az containerapp job start` request contains only resource group, Job name,
   and output format. Accept only a server-generated active drill with one
   epoch, exactly three unique records, a bounded TTL, owner/fence hashes, and
   a create-only prepare receipt. The Job must exit while all three records
   remain active.
3. **Drain.** Repeatedly start the ordinary
   `aiops-dev-ontology-discovery` template. Each pass may select at most one
   member. Read durable epoch/cursor/authorization receipts through the
   evidence identity. A deferred retry must rotate behind a later member, all
   three prepared members must terminate or close-exclude, and at least two
   execution hashes must share one epoch/snapshot lineage. Do not create or
   edit fixture records after the epoch is selected.
4. **Injection traversal.** Read the Terraform-owned coordinator UAI and exact
   `aiops_validation_fixture` tag through real ARG. Require the same resource
   and tag hashes in authoritative inventory, bounded evidence, and the
   deployed `OntologyCurator` trace. The trace must use exactly
   `list_changed_entities`, `get_entity_evidence`,
   `get_ontology_vocabulary`, and `search_relationship_history`, preserve the
   authorized scope, make zero mutation attempts, and create zero
   authoritative model edges.
5. **Cleanup.** Start `ontology-fixture-cleanup` with its unchanged template
   and no overrides. Cleanup must resolve the single active drill
   server-side, match owner/fence, remove exactly its three records and epoch,
   and retain immutable prepare/cleanup/sweep audit. Independently observe
   zero fixture connections and zero prepared epochs through the evidence
   identity. Never widen deletion when ownership cannot be proven.
6. **Maintenance.** Prove the general operator is denied, the dedicated
   maintenance grant is accepted and coordinator-reauthorized, the next run
   is full, and the following unchanged run is incremental.
7. **Publication.** Reconstruct manual intake through coordinator claim and
   publish dispatch, then publisher claim/status and a fresh API reload.
   Exercise only server-owned fixed-template stale-writer and allowlisted
   post-check controls. Require stale fence/ETag rejection, automatic rollback,
   one-shot cleanup, direct stage/validation/materialization/CAS/post-check
   receipts, and `old → new → old` convergence across API, Fabric, agent,
   export, and semantic consumers.
8. **Finalize.** Recheck template hashes, identity action sets, empty fixture
   state, retained audit, the unchanged Terraform tag, zero authoritative
   model edges, and `BLOCKED/PENDING` release for every pair.

The fixed start shape is always:

```bash
az containerapp job start \
  --resource-group <derived-resource-group> \
  --name <deployed-fixed-job-name> \
  -o json
```

Never add `--command`, `--args`, `--env-vars`, `--image`,
`--mi-user-assigned`, replica, timeout, retry, or completion overrides. Never
use `az containerapp job update` during the drill.

Use one checkpoint and one sanitized output across stages:

```bash
uv run python scripts/validate_ontology_discovery_live.py \
  --stage lifecycle --environment validation --shadow \
  --resume-file .planning/eval/ontology-deployed-lifecycle.checkpoint.json \
  --output .planning/eval/ontology-deployed-lifecycle.json \
  --max-wait-seconds 1800 \
  --assert-isolated-azure-contexts \
  --assert-deployer-only-job-start \
  --assert-evidence-read-only \
  --assert-no-runtime-job-start-grants \
  --assert-fixed-job-template-hashes \
  --assert-no-job-overrides \
  --assert-fixture-prepare \
  --assert-exact-three-records \
  --assert-validation-connection-root \
  --assert-production-registry-path \
  --assert-eligible-set-drain \
  --assert-no-post-selection-injection \
  --assert-process-replacement \
  --assert-coordinator-uai-injection-tag \
  --assert-real-arg-inventory-curator-path \
  --assert-exact-four-curator-tools \
  --assert-maintenance-authorization \
  --assert-full-then-incremental \
  --assert-fixture-cleanup \
  --assert-audit-retention \
  --assert-fixture-registry-empty \
  --assert-authoritative-model-edge-count-zero \
  --fail-on-local-substitution \
  --fail-on-missing-evidence
```

If any stage fails, preserve the opaque checkpoint and immutable server
receipts. Do not hand-edit evidence, inject replacement state, or skip ahead.
The checkpoint may contain only stage names encoded as SHA-256 step keys and
opaque evidence hashes; raw IDs, roots, tags, prompts, commands, tokens, and
errors are forbidden.

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
