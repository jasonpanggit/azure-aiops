# Ontology discovery shadow operations

## Deterministic inventory publication

Connection **Sync** saves connection-scoped discovery, not published Fabric
tables. The Terraform-managed `${base}-inventory-publication` Container Apps
Job runs full discovery for every active registered connection, refreshes
inventory, merges the exact discovery roots with the refreshed inventory,
and publishes both inventory contract tables and deterministic graph tables.
It is independent of the proposal-only Foundry curator described below.

Enable `enable_inventory_publication_job` with a reviewed immutable API image.
Keep `inventory_publication_schedule = ""` for initial manual execution.
Terraform supplies the OneLake home/registry roots, managed identity,
vault-scoped secret-read grant and `AIOPS_FABRIC_CONFIG_JSON`; the complete
JSON configuration overrides baked configuration and derives replacement
workspace/lakehouse/capacity IDs from resources. It contains no credentials.
Malformed overrides fail closed rather than falling back to deleted resources.

The inventory producer has independent opt-ins:
`inventory_publication_image_digest` pins only this Job, while
`inventory_publication_native_registry_mapping` selects the qualified two-column
registry mapping and forces Ontology definition publication off for this Job.
The API, coordinator and dedicated ontology publisher configurations are not
changed. `inventory_publication_graph_refresh_target` is either null (no refresh
environment variables) or one object containing both `workspace_id` and
`graph_model_id` UUIDs. Refresh remains ordered after completed publication under
the source lease; do not add an independent Fabric refresh schedule.

The durable `graph-refresh/state.json` receipt is not a freshness or GQL
queryability verdict. A valid accepted job is CAS-recorded with workspace,
GraphModel, source generation and job instance ID **before** polling; its phase
remains `requested` until a verified terminal result is saved. A timeout,
transport failure or lost state ownership cannot be called a definitive job
failure. The CLI reports these refresh outcomes as `ambiguous`, with
`operator_review_required: true`, and exits nonzero even when publication
completed. It never retries the POST or clears the intent automatically.
Operator review must reconcile the recorded job against the exact target and
source before permitting another refresh. An acceptance-record CAS conflict
stops polling and never overwrites another owner's record.

An accepted request adds a state revision before its terminal record: revision
numbers are CAS tokens, not a fixed two-revisions-per-run counter. Requests
rejected before acceptance need not have a job ID; an unresolved pre-acceptance
intent can also lack one. Do not infer failure or rerun from that absence.

The reviewed dev settings are in `environments/dev.native-ontology.tfvars`:
F8, daily `30 14 * * *` UTC, immutable producer image, native pair mapping and
the accepted GraphModel target. These preserve the approved live configuration,
not a claim that recurrence, capacity sufficiency or production SLOs are proven.
Generic defaults remain manual, with mapping and graph refresh disabled. A
plain apply without the dev overlay can revert the accepted schedule and SKU.
Always pass `-var-file=environments/dev.native-ontology.tfvars` **after** other
dev variable files, inspect the complete plan and retain the immutable prior
image/configuration. This source update does not authorize an apply, import,
replacement, permission change or resource deletion. Do not apply a historical
plan or default tfvars to the corrected tenant.

Back up and checksum-migrate existing local connection state before switching
the API roots. Run the job manually, wait for terminal success, verify both
table families and inventory API readback, then enable a UTC cron through a
separate Terraform plan. A started execution or successful discovery count is
not publication evidence. Preserve the previous API revision and source data
until durable readback is verified. Keep Fabric IQ/Data Agent grounding off
unless separately validated; `enable_fabric_ontology_item` controls only the
separate Fabric Ontology item, not deterministic ontology table publication.

The inventory Job and API inventory refresh share the existing `state/run.lock`
at the configured combined `storage.output_dir`. The Job holds it across
discovery, acquisition, merge and publication; API refresh acquires the same
lock rather than relying on Job replica parallelism. Connection-scoped runs
retain their independent root locks. Remote leases renew every 20 seconds
(the service lease lasts 60 seconds), and renewal stops and joins before
release. Known lease loss fails publication and prevents ingestion watermark
advancement. Caller ownership checks also reject an expired monotonic validity
deadline while renewal is blocked. Deadlines start before acquisition/renewal
requests, so network latency is not added to confirmed validity; a late renewal
success cannot revive an expired caller. Optional ownership checks also run after source staging and
before active-generation promotion; they do not replace the authoritative
ontology ETag/fence protocol or provide a new storage-side CAS guarantee.

Before enabling recurrence, use the exact immutable candidate image for a
bounded manual run longer than one lease lifetime. Verify successful renewal,
rejection of a second overlapping execution, terminal publication success,
new scoped source generation and actual provider watermark advancement.
Retain the previous good snapshot and capture API readback without mixing
API revisions. A 60-second lock, `parallelism = 1`, or a started Job alone
does not qualify overlap safety. Keep the schedule Manual if these checks fail.

For read-only comparison, `scripts/collect_inventory_evidence.py` accepts an
explicit API origin, tenant, subscription, audience, expected generation,
revision and image digest. `--snapshot-root` adds source/read-port comparison;
`--browser-receipt` compares a receipt captured by
`scripts/collect_inventory_browser.mjs` from an already authenticated loopback
CDP session. Neither collector refreshes data or imports CLI tokens into the
browser. PaaS group totals are compared through group-detail identity sets,
not equated to resource-observation counts. Software with no discovered
`Microsoft-ConfigurationData` DCR destination is unavailable, not healthy
empty; an unrelated Container Insights workspace is not that prerequisite.
Browser, refresh/last-good, graph viability and provider-watermark acceptance
remain unproved until their respective real operations are executed.

Phase 13 operates only in **shadow mode**. Model-derived relationships may be
reviewed and measured, but they must remain absent from authoritative
candidates, immutable stages, the active generation, exports, and all
consumers. There is no release, canary, allowlist, or activation option in the
live validator.

## Status storage failures

An Azure storage HTTP failure while reading authorized ontology status returns
`503 provider_unavailable`, reason `ontology_status_read_unavailable`, rather
than an empty successful run list. The error retains the request correlation
and normal configured CORS policy; untrusted origins gain no access. Provider
target identifiers and raw response text are not returned. The
`ontology_status_provider_unavailable` warning records only the provider's
status code when available.

This is an API error boundary, not a data-permission repair. The API must have
the intended read capability on its exact dedicated ontology state root.
Workspace Viewer alone does not prove OneLake file access. Reconcile effective
item data-read roles for the selected managed identity, preserving existing
roles and scope; do not redirect state into the operational Lakehouse, grant
Contributor, or widen CORS to conceal a read denial. A successful scoped
deployed read is still required for live acceptance.

Generation `validation.observed` distinguishes a durable explicit boolean
validation result from an unavailable or missing receipt. A default
`passed: false` without an observed result is **Not reported**, not an executed
failure. The proposals empty state cites a completed zero-proposal run only
when a succeeded run explicitly reports `proposal_count: 0`; missing history,
active/failed/cancelled runs and unverified empty lists do not establish that
outcome.

## Persistent API state-read policy

`ontology_api_state_read_role_contract` in `infra/terraform/outputs.tf` declares
the API apps managed identity, dedicated state workspace/item, exact
`Phase13ApiStateRead` role and `/Files/aiops/ontology/state` folder. This is an
operator-reconciled REST policy because the provider cannot safely round-trip
ManagedIdentity members. It is not an unsupported Terraform role resource or
a plan-time/local-exec writer. The existing five-item evidence contract belongs
to a different identity; never substitute that broader contract for API reads.
Existing REST reconciliation preserves unrelated policies semantically.

After the output is available from the normal validated Terraform state update,
save it with `terraform -chdir=infra/terraform output -json
ontology_api_state_read_role_contract` to a mode-0600 contract file. Do not apply
unrelated infrastructure just to emit an output. For the already repaired dev
target, the bindings are workspace `7fdda9f2-46fa-4ce5-b810-57924ae32491`, item
`340c485f-3d1c-4277-a1bd-84cdc340af47`, app MI
`1701d43c-bdc3-4ab7-9964-02cbbbc35a93`, tenant
`262a3a77-7d74-4684-8937-897d98d2a17a`. Reconfirm the actual API
`AIOPS_ONTOLOGY_STATE_HOME` and selected MI before any reconciliation.

Reuse `scripts.reconcile_onelake_data_access_roles` from an explicit operator
Python invocation, rather than the five-item CLI:

```python
import json
import httpx
from pathlib import Path
from scripts import reconcile_onelake_data_access_roles as roles

contract = json.loads(Path("api-state-read-contract.json").read_text())
assert contract["role_name"] == "Phase13ApiStateRead"
assert contract["path"] == "/Files/aiops/ontology/state"
config = Path("/absolute/path/to/approved-mode-0700-azure-cli-config")
principal_type = roles._get_principal_type_from_azure_cli(
    config, contract["principal_object_id"], contract["principal_resource_id"],
)
token = roles._get_token_from_azure_cli(config)
roles.MAX_RETRIES = 0  # Stop and review on ETag conflict.
with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
    result = roles.reconcile_item_roles(
        client=client,
        workspace_id=contract["workspace_id"], item_id=contract["item_id"],
        object_id=contract["principal_object_id"], tenant_id=contract["tenant_id"],
        role_name=contract["role_name"], paths=(contract["path"],),
        verified_principal_type=principal_type, dry_run=True,
    )
print(json.dumps(result))
```

Dry-run first; only an approved operator changes `dry_run` to false after
retaining current/desired policies, collection ETag and exact scope diff.
The existing reconciler performs server dry-run, conditional PUT and semantic
readback. Never print/export the token. A PUT can regenerate server role IDs,
including DefaultReader's ID; policy preservation is not assignment-ID or byte
preservation. Review known role-ID consumers before future updates.

For rollback, GET the current collection and ETag, remove only the exact new
API role, preserve every unrelated current policy, strip server `id`/ETag
metadata and use the supported dry-run/If-Match/readback contract. Stop on
conflict. Retained old bytes are evidence, not a stale-ID/ETag replay payload.
Neither Terraform output nor successful policy readback establishes live
authorization: require one exact-scope pinned API status read through its MI.
The 2026-10-20 repair produced HTTP200 with configured CORS; sibling denials,
other roots and full lifecycle acceptance remain separate qualifications.

## Agent-led maintenance preparation

Phase 14 builds on this shadow runtime; it does not enable model admission.
`build_production_runtime` accepts a borrowed `Curator` implementation for
controlled integration. The default remains the version-pinned Foundry curator.
The runtime closes its own default client, but callers must close injected
clients. Injection does not relax required environment values, distinct storage
roots, or the hard-shadow policy.

Every provider response is checked against the complete proposal schema and
trusted batch references before it becomes a dispatched result. Results retain
a bounded `provider_receipt` with requested/selected provider, execution
classification and hashes. Missing provider metadata is explicitly unavailable;
simulated/imported output is not live native-agent evidence. Cancellation,
generation changes, expired deadlines and lost leases reject late responses.

Native Fabric Ontology Agent unattended proposal authoring remains unestablished
on current supported-interface and identity evidence. Selecting native raises
`UnsupportedPlannerCapability` before transport; an explicit Foundry fallback is
attributed as Foundry with the native denial reason. No browser cookies, private
conversation endpoints, Act operations or definition credentials are introduced.
Native UI/MCP query success is not unattended authoring acceptance.

The executable path is recorded in
`.planning/phases/14-agent-led-ontology-maintenance/`: source corroboration and
incremental baselines, separate schema/format review, prerequisite-bound
admission, candidate-bound materialization/recovery, and governed rollout.
Legacy JSON publication must not be retargeted at the TMDL copy without the
separate compatibility/migration gates. Offline review/replay passing does not
qualify deployment or enable automatic ontology changes.

The offline source projection also supports opt-in
`aiops.dependencyResourceIds` declarations containing exact target ARM IDs and
fixed-field `AppDependencies` observations. Physical resources resolve through
existing in-scope Application membership; telemetry labels alone cannot create
identity. Monitor input requires explicit server-supplied emitter/target
bindings and an injected source reader. The fixed query and projector are not
proof that production telemetry or those bindings exist. Repeated events from
one source cannot count as independent corroboration. Stored graph baselines
advance only with successful dispatch and predecessor CAS; partial scans do not
retire unseen rows or establish a complete baseline.

## Credentialed validation

### Native-only deterministic repair

Missing native items are distinct from missing deterministic Delta tables.
Do not use `publisher_cli run-once` for a native-only repair: it consumes
intake and can replay a complete table publication.

Keep API/inventory `enable_fabric_ontology_item = false`. Set only the
dedicated publisher's `enable_fabric_publisher_ontology_item = true`, use
`ontology_publisher_environment = "production"`, and hold
`ontology_publisher_schedule_enabled = false`. This changes neither the
coordinator/fixture classification nor connection eligibility. Review a
publisher-only saved infrastructure plan, current targets, immutable image,
distinct durable capability roots and effective publisher identity access
before starting anything. No `STATE_HOME` or validation drill is permitted.
In this held native-only configuration the Job defaults to `native-preview`,
not full `run-once`; execution must explicitly supply the source-generation
argument or fail without processing intake.
Pin only `ontology_publisher_image_digest` for the repair; leave the shared
`ontology_discovery_image_digest` unchanged so coordinator/validation images
are not rolled as collateral.

Under that dedicated publisher identity, preview an explicit **ingestion run
ID**, not an expired command or inventory source-run ID:

```bash
python -m ontology_discovery.publisher_cli native-preview \
  --source-generation <latest-completed-ingestion-run-id>
```

The read-only preview checks the latest successful ingestion marker, matching
canonical Delta heads, graph validity, deterministic authority, managed typed
tables, string property/key schemas, unsupported column mapping and exact
typed-table contents. It binds only nonempty active registered entity types
and their observed relationships. Its hash includes source versions, all
binding tables, proposed definition, target and existing item definition.
Unchanged typed tables can legitimately retain earlier row `ontology_version`,
ingestion and timestamp metadata because existing Delta overwrite idempotency compares
resource/change versions. The preview accepts this only when every other
value matches the current active graph **and** the complete retained row is
proven in a completed canonical generation; it reports those retained row
versions explicitly. Unknown provenance or any content/key change is rejected.
It does not create folders, process intake, sync tables, stage generations
or change active pointers.

Render and review the proposed entities, relationships, every affected part
and binding with the operator. After explicit approval of that exact preview:

```bash
python -m ontology_discovery.publisher_cli native-publish \
  --source-generation <same-completed-ingestion-run-id> \
  --preview-hash <approved-preview-hash> --yes
```

Publication revalidates the proposal and rejects changed source/native state.
Native writes are not automatically retried. Success requires the item to
resolve and its complete definition/bindings to match actual `getDefinition`
readback, including LRO result retrieval. A created item alone is not success.
Comparison ignores JSON formatting/key order and only known Fabric export
defaults: the exact v1 schema annotations, empty entity `untypedProperties`,
absent versus null source schema, and service-owned `.platform` metadata.
All part paths, IDs, entity/relationship properties, nonempty source schemas,
table targets and key/property bindings must still match. If creation succeeds
but verification fails, inspect the existing item and compare the saved proposal
before retrying; do not blindly replay creation or relax binding checks.
Persist the preview and verified response as release evidence. This publishes
the already-completed source; it does not claim a new inventory refresh.
Leave general discovery/publisher schedules held until independently approved
command eligibility, durable intake/dispatch and scheduled behavior are proven.

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

Coordinator epochs retain ordered `selection_history` alongside member state.
Each completed selection records its cursor transition, attempt, outcome,
worker, and reauthorization receipt in the same durable state write. The
read-only collector exports only hashes and closed cursor/attempt/outcome
fields. A resumed lifecycle validator uses this history to prove that another
member progressed between a retry and its next attempt, with unchanged epoch
and snapshot lineage across workers.
The default coordinator CLI owner includes a fresh process-invocation nonce,
so separate fixed Job executions produce distinct hashed worker identities
even if the underlying container hostname is reused. Explicit `--owner` remains
an operator override and must not be set to a stable value for restart proofs.

A partial-drain resume validates the complete history from the epoch's initial
zero cursor, not from the resumed snapshot's current cursor. The resumed
snapshot must match an exact prefix of that history, including its member
attempts, outcomes and cursor. Rewritten or truncated prefixes fail closed;
newly observed selections cannot substitute for missing earlier history.

Attempt totals, epoch revisions, and sets of worker hashes alone do not prove
selection order. Older epochs without this history still load, but cannot be
used to infer fairness: retain their failure evidence and run a new governed
validation lifecycle after deploying the repaired coordinator and collector.
Local regression results are not deployed acceptance and do not unblock
Phase 03.7 or native Phase 03.8.

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

## Inventory publication and Exposure Gold

When production Exposure is enabled, registered-connection inventory publication
must pass the shared durable document store to Fabric sync. This publishes the
Exposure Gold tables and their activation pointer in addition to inventory,
bronze/silver and ontology tables. A successful inventory-only publication is
not sufficient for API readiness: the SQL readiness gate requires the Gold
schema. Keep the API candidate at zero traffic until that gate passes; do not
disable the gate to mask missing publication products.
