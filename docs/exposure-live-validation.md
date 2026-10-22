# Exposure live validation and rollout runbook

This runbook is the operational contract for promoting the persisted Exposure
read model. Promotion is fail closed: no operator may reinterpret a successful
container deployment, healthy API process, or passing synthetic test as proof
that live Exposure evidence is ready.

## Safety invariants

- Use only the authorized dev subscription and resource group for the current
  canary.
- Never print, persist, export, or place cursor signing-key values in Terraform
  state, source, shell history, logs, or evidence artifacts.
- Tenant, subscription, connection, target, digest, vulnerability, cursor, and
  raw provider payload values are scoped data. Retained evidence contains only
  aggregate counts, stable reason codes, hashes, release metadata, and pass or
  blocked outcomes.
- Container findings remain review handoffs or `no_safe_action`. They never
  invoke a patch adapter, image build, workload mutation, deployment, or other
  container operation.
- Rollback changes flags and a retained generation pointer. It does not delete
  observations, Gold history, ontology rows, audit events, or evidence.
- The Phase 13 ontology jobs keep their separately qualified immutable image.
  A global API release must never move those jobs to the global tag.

## Prerequisites

Before any shadow or canary stage, prove all of the following:

1. The deployment has an authorized active connection and can acquire AUM,
   Defender, and supported Container Insights evidence.
2. `fabric.config.deploy.yaml` contains the authoritative Fabric SQL endpoint
   metadata and uses managed-identity authentication.
3. The API image contains Microsoft ODBC Driver 18 and its runtime libraries.
4. `exposure-cursor-active` and `exposure-cursor-previous` resolve through
   versionless Key Vault references on the application managed identity.
5. Active and previous cursor `kid` values are non-secret, non-empty, and
   distinct.
6. At least one enabled Azure Monitor action group is configured. An existing
   action-group resource ID is valid when email receivers are empty.
7. A retained prior reconciled generation exists before the read lane moves
   beyond `off`.
8. The shared primitive, Overview, CVE, KB, risk-dialog, remediation, and
   browser continuity suites pass for the exact release.

## Source hierarchy

Readiness follows this order; a later layer cannot repair a missing earlier
layer:

1. **AUM acquisition** — typed success or failure, independently checkpointed.
2. **Defender evidence** — exact digest observations, with source attribution.
3. **Supported Container Insights** — exact digest and observation-time
   deployment evidence. Repository, tag, ARG-only, or inferred ownership stays
   unknown.
4. **Durable source checkpoints** — failed attempts may carry only a previously
   proven last-known-good partition.
5. **Fabric Gold** — reconciled facts, facets, summaries, evidence, and
   generation metadata.
6. **Ontology** — exact typed observation → digest → deployment → workload
   relationships for the same generation.
7. **API and web** — identical authorized scope and generation.
8. **Governed handoff** — review-only container behavior and immutable audit.

Detailed Defender subassessments remain durable Silver evidence. They are not
copied one-for-one into ontology: the ontology projects one current exposure
node per scoped immutable digest and CVE pair, references the contributing
Silver observation IDs, and preserves exact digest-to-workload edges. Portal
and API summaries group those current facts by logical image, digest, CVE,
severity, and affected workload. This keeps complete audit evidence without
making source-event cardinality the graph cardinality.

## Release preparation

Run the focused suites before building:

```bash
uv run pytest -q \
  tests/test_exposure_live_validation.py \
  tests/test_exposure_api_performance.py -x

terraform -chdir=infra/terraform fmt -check -diff
terraform -chdir=infra/terraform validate -no-color
terraform -chdir=infra/terraform test -no-color
```

Run the complete backend and web gates required by the release:

```bash
uv run pytest -q
cd web
npm test
npx tsc --noEmit
npm run lint
npm run build
npm run test:e2e
```

Build a unique immutable tag with the repository workflow. The workflow
archives committed `HEAD`, so Git sockets, ignored credentials, local state,
and untracked evidence never enter ACR:

```bash
AIOPS_ENV_FILE=web/.env.local ./infra/scripts/build-and-push.sh
```

## Terraform plan and apply

Terraform credentials are sourced only through the deployment wrapper:

```bash
AIOPS_ENV_FILE=web/.env.local \
  ./infra/scripts/deploy.sh plan -out=/secure-temporary-path/plan.tfplan -no-color
```

Review the machine-readable plan before apply. Required results:

- zero destroys;
- zero replacements;
- no Phase 13 ontology job, identity, role, workspace, Lakehouse, or capacity
  change;
- the Phase 13 ontology image tag remains explicit;
- Key Vault secret values are absent;
- only intended in-place image/configuration changes and additive alerts/jobs
  appear.

Apply only the reviewed saved plan:

```bash
AIOPS_ENV_FILE=web/.env.local \
  ./infra/scripts/deploy.sh apply -auto-approve /secure-temporary-path/plan.tfplan
```

## Qualified Fabric SQL benchmark

The qualifying benchmark runs inside the deployed API/ACA environment with the
application managed identity and ODBC Driver 18. It derives tenant,
subscription, connection, and readable generation from the deployed connection
registry and Gold pointer. Do not pass invented scope values.

```bash
python /app/scripts/benchmark_exposure_read_model.py \
  --require-ready --rows 100000 --json
```

Passing evidence requires:

- adapter `fabric_sql`, never Delta fallback;
- exactly 100,000 aggregate rows across non-empty server and container-image
  scenarios;
- bounded `page_size + 1` transfer;
- duplicate count zero and omission count zero;
- count, first-page, filtered, server, image, and keyset scenarios;
- p95 below 2,000 milliseconds;
- release, configuration, and generation binding.

Production qualification also requires at least five warmups and twenty
measured requests per target-kind scenario, and at least 100,000 total rows.
Smaller or lightly sampled production runs fail qualification. Deterministic
readers and readers with an injected connection factory remain contract-only:
their passing result never sets `production_certified` or
`production_slo_evidence`. The standard command above uses the qualifying
sample defaults; retain its adapter and qualification fields with the receipt.

If Gold schema or live metadata is missing, the command exits non-zero with a
sanitized reason. A local deterministic benchmark is useful regression
evidence but is never production certification.

## Live validator

Run the validator in the same managed environment:

```bash
python -m scripts.validate_exposure_live --require-all --json
```

The retained report must prove:

- AUM, exact Defender digest, supported Container Insights, Fabric SQL,
  persistence, and ontology outcomes;
- matching API and web scope identity;
- shared primitive, Overview, CVE, KB, and risk-dialog suite artifacts;
- active/previous Key Vault refs, 15-minute cursor TTL, and 30-minute previous
  key overlap;
- governed links and risk outcomes;
- the exact three executable action IDs;
- zero container operation calls;
- one-cycle telemetry and alert routing;
- qualified 100k benchmark;
- exact digest-to-workload Phase 4 path.

The validator rejects credential-like keys and raw payload fields before it
emits a report.

### Generation-bound acceptance manifest

The validator checks consistency of supplied evidence; a passing synthetic
fixture is not provider attestation. Collect live receipts with the existing
Gold/query pipeline and retain their sanitized references. Never fill a missing
receipt with a test result, historical rollout, or invented operator signature.

`binding.source_run_ids` requires non-empty `aum`, `defender_digest`,
`container_insights`, `publication`, and `benchmark` run IDs. The corresponding
source sections carry matching `source_run_id` values; `persistence` and
`ontology` carry the publication run ID, and `benchmark` carries its run ID.
The binding generation must match `persistence.generation_id`,
`ontology.generation_id`, `benchmark.dataset.generation_id`, and
`phase4.digest_to_workload.generation_id`.

The exact traversal additionally requires positive integer
`silver_workload_deployments`, `digest_to_deployment_edges`, and
`deployment_to_application_edges`. Its non-negative integer `represented`,
`unknown`, and `excluded` counts must sum to `total`, with `represented > 0`.
Booleans, numeric strings, nulls, and missing counts are not evidence.

Retain the production benchmark output, not just its pass flag: exactly
100,000 server plus container-image rows; matching returned and unique counts;
zero duplicate/omission counts; both target-kind p95 measurements strictly
below 2,000 ms; and bounded `page_size + 1` transfer with no full-table
materialization or Delta fallback. These fields use the existing benchmark
script's `dataset`, `full_walk`, `timings`, `query_contract`, and `work` shapes.

`rollout` requires `status: pass`, the binding `generation_id`, matching
`candidate_generation_id`, and a distinct retained `prior_generation_id`.
Its `canary` and `rollback` objects each require `status: pass`,
`observed: true`, a timezone-aware ISO `observed_at`, and distinct non-empty
`evidence_ref` values. Canary's `active_reader_generation_id` is the candidate.
Rollback's `from_generation_id` is the candidate and its
`active_reader_generation_id` is the retained prior generation. Rollback must
be observed after canary, with `preserve_evidence: true`,
`destructive_actions: []`, and `post_rollback_health: pass`.

`operator_checkpoint` requires `status: approved`, `operator_authorized: true`,
`authenticated: true`, the binding `generation_id`, `observed_at` at or after
rollback, and a non-empty sanitized `evidence_ref`. All eight Plan 28 checklist
keys must be `pass`: `authenticated_overview`,
`defender_and_container_evidence`, `cve_kb_detail`,
`source_completeness_and_freshness`, `exact_workload_traversal`,
`governed_review_only_container_handoff`, `generation_and_aggregate_match`,
and `secret_and_raw_payload_absence`. A machine check cannot manufacture this
operator outcome. Historical nested checkpoint fields are not current approval.

The report separates three gates to avoid a circular deployment prerequisite:
`automated_preflight_ready` excludes future rollout and operator evidence;
`operator_checkpoint_ready` additionally requires observed canary/rollback;
`phase4_ready` requires every check, including the authenticated operator.
Missing later evidence still produces `status: blocked` and exit 2 with
`--require-all`; neither preflight flag authorizes a rollout or closes the phase.

## Promotion order

Advance one lane at a time. Re-run all prerequisites after each new revision.

1. `off` for write, read, web, and handoff while prerequisites are incomplete.
2. `shadow` writer with a new immutable generation.
3. Verify source coverage, Gold reconciliation, low-cardinality telemetry,
   one-cycle alerts, UI/API contract, and the qualified benchmark.
4. `canary` reader with explicit candidate and retained rollback generation.
5. `canary` web.
6. `canary` governed handoff.
7. `on` reader, then web, then handoff only after a complete canary cycle.
8. Keep the prior generation retained for at least seven days and at least two
   successful generations.

`ExposurePromotionEvidence` must pass every prerequisite. A failed source,
reconciliation, alert, telemetry, SLO, UI/API, live-validation, ingestion,
read, or key-rotation check selects the rollback generation and reports no
destructive action.

## Alerts and telemetry

Exposure alerts evaluate every five minutes over exactly one 30-minute
ingestion cycle and trigger after one failing period:

- effective row floor;
- last-known-good row drop;
- source failure or staleness;
- merge conflict;
- enrichment quality;
- represented coverage;
- semantic reconciliation drift;
- query latency or error budget.

API/web replica and provider-health rules share the configured action group.
The custom-metric queries include an empty typed relation so rules can be
created before `AppMetrics` materializes; real metrics remain the only rows
that can satisfy an alert predicate.

## Cursor key rotation

1. Generate the new key only in a bounded private ACA job using the application
   managed identity.
2. Move the old active value to the previous Key Vault secret and the new value
   to active. Never read either value into Terraform.
3. Assign new distinct non-secret `kid` metadata.
4. Deploy one revision with both versionless refs.
5. Prove active issue/verify, previous verify before 30 minutes, previous
   rejection at 30 minutes, and cursor expiry at 15 minutes.
6. Retire previous only after the overlap and after no rollback revision needs
   it.

## Restart conflicts

A cursor is bound to scope, filters, sort, page size, and generation. If the
generation is no longer retained, return the typed restart conflict and send
the user to the first page. Never silently rebase a cursor onto the current
generation.

## Rollback

On any failed prerequisite or runtime health check:

1. Set read, web, and handoff to `off` or select the retained rollback pointer.
2. Leave writer history and all observations intact.
3. Confirm the API and web return to the same prior generation.
4. Verify alerts remain enabled and the cursor previous key still covers the
   rollback revision.
5. Record only sanitized release, generation-hash, reason-code, count, and
   timing evidence.

The current blocked or passing live result is retained at
`.planning/phases/03.1-exposure-reliability-and-scale/03.1-19-LIVE-EVIDENCE.json`.
