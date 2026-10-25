# Agent-led ontology maintenance: offline verifier and closed owner handoff

## Current decision and authority

**Offline qualification only. Production admission and live acceptance are BLOCKED.**
The supported proposed unattended implementation branch is **Foundry proposals +
deterministic governance**, not native Fabric authoring. The user's autonomous
execution direction selects this implementation path; it does **not** authenticate
the ontology steward, security owner or Fabric governance steward, attest an
environment, or approve an exact pair release. Native remains disabled.

Migration is **none**: no exact migration request, full old/new captures, or
operation-specific approvals exist. This is not “approved migration.” Every
schema operation remains review-only, initially description-only. No retargeting
of the original `191c9b47…`, its separately recorded copy
`bb479201-8ab1-4fde-ab6c-9f9a16477115`, or the analytical model is authorized.
The original full item ID is unknown; do not expand its prefix. The recorded
copy's 163 TMDL parts are not present as a qualified full capture. Synthetic
small TMDL fixtures cannot stand in for them.

**Unified Deployment is the sole cloud rollout owner.** Existing governed
validators own live collection. This runbook contains no deployment, grant,
Job-start, Fabric-definition, item-copy, browser-auth or tenant-policy commands.
There is no second scheduler or collector lane. All Phase 14 changes except
Plan 01 are outside the frozen 338 source cutoff; do not add them to its
temporary release package. A future immutable Phase 14 release is a separate
owner-qualified handoff, not an amendment of that package.

## Executable local verification

### Protected-row incremental maintenance

Incremental reconciliation preserves the prior graph row and its hash when an
identity is explicitly unresolved or stale, even in an otherwise complete scan.
An absent protected row is not a retirement; a changed protected row does not
replace last-known-good evidence; a new protected row is not admitted. Hash
application and graph replay follow the same rule. A later complete observation
without that protection can update, admit or retire the row normally.

This preservation rule does not grant publication authority or qualify native
unattended authoring. Retirement still requires complete authoritative coverage;
partial scans preserve unseen rows, and existing release gates remain unchanged.

### OneLake Catalog discovery input

OneLake Catalog can supplement source discovery with Fabric item identifiers,
types, names, descriptions and containing workspace metadata. The
[Catalog Search API](https://learn.microsoft.com/en-us/rest/api/fabric/core/catalog/search)
is preview and supports user, service-principal and managed-identity callers,
subject to the caller's authorized access. Discovery is not data access.
`fabric.catalog_source.FabricCatalogSource` implements bounded candidate
acquisition using the existing credentialed Fabric transport. It is not enabled
in the coordinator or a scheduled job, and is not a live qualification receipt.

For an existing `FabricClient` and a previously resolved, explicitly allowed
workspace ID:

```python
from fabric.catalog_source import FabricCatalogSource

observation = FabricCatalogSource(
    client,
    workspace_id=allowed_workspace_id,
    page_size=100,
    max_pages=10,
    max_items=1000,
).fetch()
evidence = observation.to_dict()
```

The adapter returns only after bounded pagination finishes; errors propagate
without partial success output. It rejects duplicate items, repeated tokens,
malformed entries, unsupported continuation URLs and cross-workspace results.
Serialized evidence records observation time, page count, candidates and fixed
`coverage: partial`, `authoritative: false`, `requires_direct_verification: true`.
`search_complete: true` describes paging only, not source freshness or coverage.
No graph mutation or proposal approval is performed by this adapter.

For opt-in direct item metadata checks, call `fetch_verified()` instead of
`fetch()`. It first completes bounded search, then issues one sequential
[Core Get Item](https://learn.microsoft.com/en-us/rest/api/fabric/core/items/get-item)
request per candidate using the same client and allowed workspace. Search
limits bound the number of items checked; the Fabric transport's existing
attempt limit bounds retries. All requests carry the Catalog skill header.

Direct responses must match the requested item ID, workspace ID and catalog
item type. Current names and descriptions are retained separately from indexed
metadata, with an endpoint, timezone-aware verification time and a metadata
change flag. Empty or malformed responses, access/deletion errors, unsupported
item APIs, identity/type drift and invalid clocks fail the whole call without
partial success output. They do not trigger retries outside the existing
transport policy, source fallback or retirement.

The resulting evidence retains the original `catalog` observation and adds
`verified_items`. Its `verification_scope: item_metadata_only` and
`requires_schema_verification: true` explicitly limit what was checked;
top-level `requires_direct_verification: false` means only that every returned
candidate passed the direct item metadata check. It does not establish schema,
lineage, underlying data access or publication approval. Empty results still
have partial coverage and never prove absence. Search and sequential GETs are
not an atomic snapshot; an item can change after its check. No caller identity
qualification, scheduled collector or ontology writer is enabled by this API.

### Read-only executable Catalog qualification

The finite command below runs `fetch_verified()` with the existing Fabric
runtime configuration and its managed-identity or service-principal credential:

```bash
PYTHONPATH=src .venv/bin/python -m fabric.catalog_cli \
  --config fabric.config.yaml --page-size 100 --max-pages 10 --max-items 1000
```

`AIOPS_FABRIC_CONFIG` supplies the default config path; the existing
`AIOPS_FABRIC_CONFIG_JSON` runtime override remains supported by the config
loader. Workspace scope is pinned to that configuration's `workspace_id` and
cannot be overridden with a command-line workspace or credential. The command
only searches Catalog and reads item metadata. It does not list domains, change
permissions, create proposals, write baseline state or start a scheduled job.

Successful stdout contains one JSON advisory report with the configured auth
mode and verified evidence. This is metadata qualification, not full ontology
maintenance acceptance. A caught configuration, authentication, transport or
metadata failure returns exit code 1, emits a sanitized failure stage on stderr
and emits no partial stdout. HTTP status failures additionally include only
the numeric `http_status`; non-HTTP failures do not invent a status or cause.
Exceptions, credentials, request URLs and provider bodies are not included in
failure reports. Store successful output only in an
appropriately protected operator evidence location; item metadata can be
sensitive. HTTP retries and per-request timeouts use the existing Fabric
transport; page/item bounds are not a whole-command wall-clock deadline.

The sole deployment operator must qualify the command against the exact
deployed image and existing workload identity before any scheduler integration.
A local fixture pass or signed-in-user test cannot establish managed-identity
access or prove that this command ran in a deployed workload.

### Advisory metadata maintenance deltas

Supply `--baseline /protected/local/prior-catalog-report.json` to compare a prior
successful CLI report with a new directly verified observation. Without that
option the existing command and report shape are unchanged. The baseline is
read-only: the CLI does not create or overwrite a baseline file.

The saved report must be a successful, structurally consistent verified
observation for the configured workspace and auth mode. Parsing checks closed
fields, real JSON booleans, aware timestamps, matching unique catalog/direct
item identities, workspace/type/endpoint agreement and metadata drift flags.
Duplicate JSON keys, malformed reports and inputs above 2,000,000 UTF-8 bytes
are rejected before network access. Comparison supports at most 1,000 items
per observation. A prior report's `metadata_delta` is ignored: only its raw
verified evidence is baseline input, so comparison output can be reused safely.

The successful report adds `metadata_delta`, containing deterministically
ordered `added`, `changed`, `unchanged` and `unresolved` items, explicit
before/after metadata and changed field names. Comparison uses direct item
metadata, not potentially stale indexed descriptions. `retired` is always
empty: an unseen item has reason `not_observed`, never presumed deletion.
Type changes are advisory review evidence, not automatic schema migrations.
The current search cannot predate the prior item's latest verification time.
Canonical SHA256 digests bind both observations, independent of item ordering;
they provide integrity references, not signatures or approval.

This is a local advisory baseline, not an authenticated provenance attestation.
Equal auth modes do not prove equal principals or permissions; differing
caller visibility remains a reason not to retire missing items. Metadata is
untrusted content and must not be executed or treated as instructions. The
CLI generates no ontology proposals or stable-ID mappings and grants no
publication authority. Schema/lineage inspection and steward/release gates
remain required. A comparison error emits no partial success stdout and has
sanitized failure stage `catalog_comparison`.

Use `POST /v1/catalog/search` with the explicit item-only filter
`WorkspaceId eq '<configured-workspace-id>' and Type ne 'Workspace'`
and bounded page size (the API permits 1..1000). A workspace-only filter can
also return a valid Workspace entry without item hierarchy, which cannot be
verified with Core Get Item. Exclude it in the request rather than silently
discarding response rows; a non-item or out-of-scope entry returned despite
the filter still fails the whole observation. Page using the returned
`continuationToken` alone: it carries the initial filter, search and page size,
and must not be combined with a new filter or search. Enforce total page/item
limits and reject malformed, repeated-token or out-of-scope responses rather
than treating incomplete enumeration as authoritative. Skill-driven audit
requests include `x-ms-fabric-skill: onelake-catalog-govern-cli`.

Treat these results as advisory candidates only. Resolve each candidate through
the relevant direct workspace/item API before inspecting its schema or lineage
and proposing ontology changes. Record the workspace/item IDs, caller scope,
observation time and direct-verification evidence with the proposal. Catalog
metadata must not be interpreted as a sensitivity label, endorsement, data
entitlement, current schema or fresh lineage.

The catalog index may lag by up to 24 hours and omits some item types. A missing
search result therefore cannot retire a row, mark a baseline authoritative or
prove that a source was deleted. A catalog-only observation must remain
non-authoritative even after all search pages are consumed. Direct source
coverage, existing baseline reconciliation and steward/release gates still own
maintenance decisions. Before enabling a collector, qualify the actual
workload identity, expected item coverage and pagination in the target workspace.

From the repository root, without plugin autoload, bytecode or pytest cache:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q \
  tests/test_ontology_maintenance_release_evidence.py \
  tests/test_ontology_discovery_live_evidence.py -x

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  scripts/validate_ontology_agent_maintenance.py \
  --mode live-release \
  --input .planning/phases/14-agent-led-ontology-maintenance/14-RELEASE-REQUEST.json \
  --output .planning/phases/14-agent-led-ontology-maintenance/14-LIVE-GATE.json
```

The second command is an intentional **nonzero blocked precondition check** with
current inputs. It performs only local reads and writes the specified report.
It does not collect evidence, sign, deploy or enable anything. A request is not
an attestation. Do not mask its exit status when using it as a release gate.

`--mode offline-qualification` is also supported with the same required
`--input` / `--output`. Positive saved offline artifacts are generated only
inside isolated pytest temporary directories with injected test trust. The
tests actually exercise the file-reading CLI and prove offline PASS, native
UNSUPPORTED, prerequisites SIMULATED_PASS, migration NONE, admission/live BLOCKED.
Nothing in production can select those keys through a CLI flag or input field.
Without an authenticated offline artifact the actual report says PENDING, not
PASS merely because a local test suite passed.

Reports separate `offline`, `native`, `prerequisite`, `migration`, `admission`,
`live`, and `authentication`. Local repository diagnostics are explicitly
non-authoritative. A live-schema positive test proves the verifier is not an
always-failing stub; its synthetic keys, corpus and “live” receipt fields are
test schema cases, never retained as actual live acceptance.

### Offline replay of saved Catalog observations

To reproduce a delta without another Fabric read, supply two protected local
full reports to the separate offline command:

```bash
PYTHONPATH=src .venv/bin/python -m fabric.catalog_compare_cli \
  --baseline /protected/local/prior-catalog-report.json \
  --current /protected/local/subsequent-catalog-report.json
```

This command does not load runtime configuration, acquire credentials, call
Fabric or modify either input. It reuses the same closed report validation,
2,000,000-byte UTF-8 limit per input, 1,000-item observation limit, workspace/
auth-mode agreement and chronological checks as the live comparison. Both
inputs must be full successful verified reports, not prior delta summaries.
Derived `metadata_delta` fields on either input are ignored. Save a genuinely
subsequent observation: a report's search can precede its own final direct
verification, so replaying the same report on both sides can fail chronology.

Success emits `status: advisory_metadata_compared`, `mode: offline`,
`verification_performed: false` and the deterministic `metadata_delta`.
It does not emit a new `advisory_metadata_verified` report and cannot itself
be reused as an observation baseline. Input validation failures exit 1 with
sanitized `failure_stage: saved_report_validation`; incompatible comparisons
use `catalog_comparison`. Neither failure emits partial success stdout.

Offline replay proves only that the saved evidence yields that advisory delta.
It establishes neither fresh access nor the authenticity, principal identity
or freshness of the supplied reports. Missing remains unresolved, `retired`
remains empty, and schema/steward/publication gates remain unchanged. The
existing live `fabric.catalog_cli` command is unaffected.

### Exact Phase13 closeout reconciliation

The required corpus is still **22 numbered plans and summaries**, not21 and
not a count padded with targeted review artifacts. Historically only plans
01..21 and summaries01..20 existed, with Plan20 partial. Newly assigned
Plan22 closes the accepted evidence chain; its plan is not a completion receipt.
Accepted Plan20 must precede Plan21; accepted Plan21 must precede Plan22.
For live purpose, Plan22 must have `accepted: true`, genuine `started` and
`completed` UTC times, and `plan21_acceptance_digest` equal to SHA256 of the
exact accepted Plan21 summary bytes. The same authenticated corpus binds those
bytes for the coordinator, publisher and local saved-evidence CLI.

`phase13_count_diagnostic` additionally distinguishes `missing_plans`,
`missing` summaries, `unfinished_summaries` and `verification_status`.
`LOCAL_ONLY` means only that local inventory checks passed; it cannot turn
failed authentication into success. Missing/malformed evidence reports
`BLOCKED`; no summary, signature or cloud evidence is generated.
The original strict 20->21 gate and all quality/deployment/trust requirements
remain mandatory. Genuine Plan20 lifecycle and Plan21 API/UI/RBAC acceptance
are the next executable predecessors, not blanket approval substitutes.

## One authentication contract, not a CLI interpretation

The coordinator and publisher use `MaintenanceReleaseReader.read`; the CLI
uses its `read_saved` seam. Both invoke **the same**
`verify_maintenance_attestation` in
`src/ontology_discovery/maintenance_release.py`. `read_saved` additionally
requires the whole saved envelope, including signatures, to equal the freshly
read server-pinned envelope. Each invocation reloads release/control and time.
There is no cached CLI authorization and no CLI-specific prerequisite parser.

The CLI accepts no trust, key, control, clock or artifact-root arguments. Only
the existing operator/server-owned `ONTOLOGY_MAINTENANCE_TRUST_CONFIG` public
configuration is used by `build_production_reader`. It pins purpose=live-release,
environment, immutable implementation, identity/template/root capabilities,
issuer/approver public keys, artifact root, release path and control path.
Offline/test purpose or key origins are rejected by production composition.
Do not supply private keys, browser tokens, passwords or credentials in this
configuration, request or output. Access to the server configuration remains
an operator security boundary, not a client-supplied authorization mechanism.

Attestations use Ed25519, a pinned release-attestor identity, separate role keys
for `ontology_steward`, `security_owner`, `fabric_governance_steward`, exact
payload-bound signatures, reasons, expiry and current revocation revision.
Wrong issuer, signature, environment, implementation, deployment acceptance,
approval, expiry, revocation or artifact bytes deny both readers. Release
operations remain only `admit` / `restore`; no schema write is added.

For live purpose the shared verifier additionally enforces:

* Tenant `262a3a77-7d74-4684-8937-897d98d2a17a` and subscription
  `890c9bfc-d09c-4143-9ce5-465e75e3eecc`.
* Both prerequisite targets, never a caller-selected subset. Phase 03.7:
  03.1 summaries 19/20, 07 summaries 01–06, all eleven 09 summaries, and
  13 summaries 01–22. Phase 03.8: 03.7 summaries 01–12, 11 summaries
  01–16, 13 summaries 01–22, and **all its own plans/summaries**.
* Unqualified `status: passed` verification for every inherited phase; no
  waiver/waived, deferral/deferred, conditional acceptance/conditional_acceptance,
  human_needed or gaps_found markers. Summaries need completed/passed status.
* Exact current summary/verification digests and all corresponding current
  plan digests. `plan_manifest_digest` and `inherited_preconditions_digest`
  both bind the canonical sorted `(relative path, sha256)` plan corpus.
  These include the independent 03.1 live blocker; no checkbox receipt erases it.
* Plan 20's summary/finalization artifact SHA-256 is referenced in Plan 21's
  frontmatter as `plan20_finalization_digest`; both have `accepted: true`.
  A timezone-aware Plan 20 `completed` must be **before** Plan 21 `started`,
  and Plan 21 `started <= completed`. Narrative mention or completion-date
  ordering alone cannot establish this live prerequisite.
* The unresolved Phase 13 22-summary/count contract is upstream-owned.
  Twenty currently retained summaries and `gaps_found` cannot pass. Never
  lower 22 to 21, supply a narrative waiver, or manufacture the missing plan.
* Accepted deployment identity/template/root/immutable-image evidence must
  match the exact running Phase 14 implementation and tenant/subscription/
  connection/workspace/item. Source merge, historical wrong-target rollout,
  local recovery tests and an unaccepted signed deployment do not qualify.
* The inherited pair-specific floor is unchanged: at least 30 shadow days,
  200 expert adjudications, no critical failure, escalation recall 1.0,
  recall >=0.90, Wilson lower precision bound >=0.98, AI-spec gates, matching
  provider/model/prompt/schema/policy lineage and fresh evaluation. Existing
  snapshot checks remain mandatory; separate live slice/citation/cost records
  are also required, not substituted with overall precision.

### Owned live receipt format

This is a **local saved evidence contract**, not an invented Fabric API.
The signed release's `qualification.artifacts` is a list of `{kind, path, sha256}`.
Paths resolve strictly within the pinned artifact root. Each file is an
Ed25519 envelope with `algorithm`, `key_id`, `payload`, `signature`. Its payload
has `kind`, `origin=live`, `collector_id`, `source_id`, `capture_id`,
`result_digest`, `observed_at`, `expires_at`, `binding`, `measurements`.
`result_digest` is the shared canonical JSON digest of the measurements.
`binding` is the canonical digest of the release payload excluding `approvals`
and `qualification`; it binds environment, exact release target/lineage,
implementation/deployment/prerequisites, evaluation and time window.

Collectors must have pinned `evidence_collector` keys distinct from the release
attestor and approvers. Revoked keys, stale/future receipts, wrong bindings,
local/offline origins and altered file hashes deny. Ownership labels and
`passed: true` are not measurements. The signed enclosing release binds the
exact receipt bytes and role approvals; it does not create missing observations.
The five consumer collectors/source IDs/capture IDs/result digests must differ.

Required receipt kinds and content:

| Kind | Required attributable content |
|---|---|
| scope_security | Exact scope-denial, injection and identity-matrix result digests |
| source_discovery | Independent declaration capture, AppDependencies capture, exact directed pair digest |
| restart_replay | Equal baseline/replayed digests and different process identities |
| target_preservation | Complete actual capture, normalized readback, retained predecessor, exclusive-writer, rules/history disposition digests |
| quality | Adjudication, slice and citation result digests, exact evaluation digest |
| budget_cost | Usage, actual price, latency samples and limits digests; unknown price is not success |
| kill_revoke | Kill, revocation and no-later-write receipt digests |
| stale_writer | Ordered loser/winner fences and retained winner-products digest |
| products | Exact candidate digest, catalog digest, complete registered product table list with row hashes and pinned Delta versions |
| recovery_postcheck | OLD/NEW/restored digests, restart process, complete OLD/NEW/restored product lists and catalog |
| recovery_cas | Same, after materialize-before-actual-failed-CAS, not just an injected pre-CAS exception |
| deployment | Accepted decision, exact implementation/identity/template/root, immutable image and exact target digest |
| consumer_api/fabric/agent/export/semantic | Independent generation/product/query/response observations on five direct surfaces |

Product lists must equal the actual canonical + typed entity + all allowed
typed relationship + health + quality product registry, including empty
products. Recovery requires OLD membership hashes restored for every table,
changed products advancing OLD→NEW→restored Delta versions, and a genuinely
novel `Application depends_on Application` typed product in NEW. The catalog
is separately fingerprinted. Do not substitute row counts, source replay,
one receipt repeated across consumers or endpoint-only hashes.

Plan 06's real local product/restart tests and example hashes are offline
qualification only. Remote sink fencing, actual deployed products, runtime
bindings and five independently observed deployed consumers remain unqualified.
Existing production composition remains fail-closed on unapproved maintenance
observer/materializer bindings; this verifier does not wire or enable them.

## Research OQ-1 through OQ-5: explicit dispositions

| Gate | Disposition | Accountable owner roles | Required reopening evidence |
|---|---|---|---|
| OQ-1 / G14-01/02 | NOT ESTABLISHED → native DISABLED | Provider-integration maintainer, security owner | Current first-party public operation/protocol/version, unattended identity/lifecycle/scope, bounded cancel/retry, preview-risk/retention/region consent, implemented qualified Curator adapter |
| OQ-2 / G14-03 | NOT ESTABLISHED → native DISABLED | Provider-integration maintainer, ontology steward | Supported bounded complete structured output with real citations, exact endpoints/direction/base/diff, adapter tests |
| OQ-3 / G14-07 | UPSTREAM-OWNED PENDING/BLOCKED | Phase 13, 03.7, 03.8 and 11 owners; Unified Deployment; security owner | Exact inherited corpus/count/order/acceptance, corrected-target immutable deployment and live trust/attestation issuance |
| OQ-4 / G14-04/06/08 | Initial class chosen offline; exact live pair PENDING | Ontology steward, security owner, Fabric governance steward | `Application depends_on Application` from Plan 02 exact declarations + independent AppDependencies; exact endpoints/scope/lineage, quality window and signed approvals. Description-only schema tracer stays review-only; all schema execution needs a separate rubric/release |
| OQ-5 / G14-06/09 | Target-specific preservation/concurrency PENDING | Publisher maintainer; Unified Deployment; Fabric governance steward | Full real legacy/TMDL captures, unknown-part/ID preservation, rules/history/bindings disposition, exclusive writer, normalized readback, predecessor physical restore in both failure windows across restart, consumer reconnection/old-new-old |

Current research:
`.planning/phases/14-agent-led-ontology-maintenance/14-RESEARCH.md`
(2026-10-19, recheck by 2026-10-26 or before a native decision).
First-party references include:
* https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-ontology-agent
* https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-ontology-mcp-server
* https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq
* https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition

No new documentation/network probe was performed in this execution. Delegated
UI/MCP query success, definition REST identity support, cookies/private endpoints,
narrative output, expired delegation and fabricated adapter receipts do not
qualify native unattended authoring. A real new supported contract needs an
exact adapter qualification plan extension, not a receipt toggle. Attended
suggestions may be imported with imported provenance, never scheduled native success.

## Closed bounded owner request and later acceptance

`14-RELEASE-REQUEST.json` records known local paths/digests, known corrected
tenant/subscription, proposed Foundry branch, migration=none and missing fields
as null. It is **not submitted/endorsed/executed**, not a MaintenanceRelease,
and contains no signatures or fake owner acceptance. Local artifact hashes
identify source records only, not trusted deployments.

There is no polling or wait loop: owner wait budget is zero in this offline
handoff. Missing evidence produces an immediate nonzero gate. Future owners
must provide bounded deadlines/expiry and exact attestations for the existing
default-off→shadow→bounded canary→explicit enablement stages; every stage is
currently disabled. Kill/revoke and separate restore authority are required.
Expiry, revocation and changed bytes must be rechecked at invocation,
admission/dispatch, stage, materialization and CAS; a previous CLI PASS is not
permission to skip a runtime read.

For a future migration, obtain a **separate** exact request digest and schema/
base/format/target authorization. Capture every real old/new part, retained
predecessor, stable IDs, rules/history/custom binding disposition, normalized
semantic diff, exclusive-writer proof, reconnect plans, bounded readback/replay/
restore and OLD/NEW/OLD five-consumer evidence. Pointer CAS does not make
Fabric definition replacement atomic. Missing enforceable exclusion or restore
keeps migration closed. This relationship-only verifier cannot approve it.

Only after Unified Deployment and the existing collectors deliver accepted
authenticated receipts should the owner import them into the pinned local
artifact root and rerun the command above. Do not repeat cloud collection here.
Record receipt paths and exact hashes in `14-ACCEPTANCE.md`, together with
PASS/PENDING/BLOCKED per independent gate and owner disagreement review.
Until then Task 3's precondition is unmet and the phase is not live-complete.
