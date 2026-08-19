# Hermes Operations Graph — Product Backlog

## Backlog conventions

- Priority: `P0` foundation/blocker, `P1` MVP, `P2` expansion, `P3` optional.
- Status for this discovery deliverable: all implementation items are `Proposed`.
- Every story must preserve source-system authority and avoid raw telemetry duplication.
- A story is not done until security, observability, reconciliation, rollback, and documentation are addressed.

## Epic E0 — Architecture and governance

### HOG-001 — Approve system-of-record matrix (`P0`)

**Outcome:** named owner and precedence for each entity/property/relationship.

**Acceptance criteria:**

- ARG is approved as Azure resource authority.
- ServiceNow/alternative authorities for applications, services, teams, incidents, and runbooks are explicit.
- Sentinel vs ServiceNow incident correlation rules are documented.
- No source is treated as authoritative merely because it is easiest to query.

### HOG-002 — Approve ontology v1 (`P0`)

- All eight entity and six relationship types are approved.
- Every edge has the four mandatory metadata fields.
- Allowed endpoints, temporal semantics, and lifecycle rules are signed off.

### HOG-003 — Threat model and data classification (`P0`)

- Model prompt-injection, overprivileged MCP, source data leakage, identity collision, and graph poisoning.
- Classify every projected field and prohibit secrets/raw telemetry.
- Define human approval boundary for mutations.

### HOG-004 — Fabric preview decision gate (`P0`)

- Validate tenant/capacity availability, legal/support acceptability, deployment lifecycle, refresh behavior, limits, and rollback.
- Record go/no-go and fallback to canonical OneLake tables plus supported query experience.

## Epic E1 — Platform foundation

### HOG-010 — Managed identity and RBAC design (`P0`)

- Separate discovery, stewardship, publication, and agent identities.
- Produce least-privilege role matrix and access-review process.
- Azure MCP discovery profile is read-only and namespace-filtered.

### HOG-011 — Environment and network design (`P0`)

- Define dev/test/prod isolation, tenant/subscription scopes, private networking, DNS, egress, and source allowlists.

### HOG-012 — OneLake curated contract (`P0`)

- Define entity, assertion, evidence-reference, alias, steward-decision, and run-watermark tables.
- Confirm that only compact projections are stored.
- Define retention, partitioning, and replay.

### HOG-013 — Platform observability (`P0`)

- OpenTelemetry/Application Insights signals for runs, watermarks, failures, quality, and publication lag.
- No custom telemetry backend.

## Epic E2 — Resource Discovery Engine

### HOG-020 — ARG scope and baseline queries (`P0`)

- Management-group/subscription scope approved.
- Queries cover Resources and required extension tables.
- Paging, throttling, partial failure, and sovereign-cloud behavior tested.

### HOG-021 — ARM identity normalization (`P0`)

- Case-insensitive matching and tenant scoping tested.
- No merge by display name.
- Alias changes are reversible.

### HOG-022 — Change-aware discovery (`P1`)

- Use source-supported resource change data and periodic reconciliation.
- A failed run cannot delete or expire resources.
- Full-scan recovery path exists.

### HOG-023 — Resource projection quality gate (`P1`)

- Compare counts/scopes against ARG.
- 100% of records have source ID and last observed timestamp.

## Epic E3 — Dependency Discovery Engine

### HOG-030 — Declared Azure topology mappings (`P1`)

- Map approved native resource references into `hosts`/`dependsOn`.
- Every mapping has an evidence definition and tests.

### HOG-031 — Application Insights dependency summaries (`P1`)

- Query aggregate dependency evidence only.
- Stable endpoint mapping, evidence windows, sampling caveats, and noise filters documented.

### HOG-032 — OpenTelemetry semantic identity (`P1`)

- Use governed `service.name`, `service.namespace`, `service.instance.id`, cloud/resource attributes.
- Instance churn does not create application churn.

### HOG-033 — Dependency confidence calibration (`P1`)

- Labeled validation set and precision/recall targets agreed.
- Low-confidence relations remain proposals.
- Staleness/decay policy tested.

## Epic E4 — Business Mapping Engine

### HOG-040 — ServiceNow service/ownership adapter (`P1`)

- Read only approved fields/tables through supported API/connector.
- Retain native sys IDs and ACL behavior.
- Do not mirror the CMDB.

### HOG-041 — Governed Azure tag mappings (`P1`)

- Maintain allowlist and value normalization.
- Missing/malformed tags create quality findings, not invented mappings.

### HOG-042 — Entra team resolution (`P1`)

- Resolve approved group IDs/service-principal ownership.
- Prefer Team entities; minimize personal data.

### HOG-043 — Azure DevOps mapping (`P2`)

- Map organizations/projects/teams/repos/pipelines to approved Applications/Runbooks.
- Respect org boundaries and API throttles.

### HOG-044 — Steward review queue (`P1`)

- Review candidates show evidence, score, source, proposed change, and blast radius.
- Decisions are auditable, reversible, and can expire.

## Epic E5 — Incident Learning Engine

### HOG-050 — Sentinel incident projection (`P1`)

- Use supported incident/API/LAW surfaces.
- Preserve incident ID, severity, status, times, source link, and affected references.
- Do not copy full alert/event payloads.

### HOG-051 — ServiceNow incident projection (`P1`)

- Incremental read with ACL-aware fields and deletion/closure semantics.
- Redact descriptions before model use.

### HOG-052 — Cross-system incident correlation (`P1`)

- Correlate only by explicit references first.
- Temporal/title similarity remains proposed.
- False merge can be reversed without losing source incidents.

### HOG-053 — Impact learning (`P1`)

- Emit provisional `impacts` links during incidents.
- Re-score after resolution/post-incident review.
- Agent can explain evidence and observation time.

### HOG-054 — Mitigation learning (`P2`)

- Link approved Runbook/Patch artifacts.
- “Suggested” is distinct from “executed” and “successful.”

## Epic E6 — Findings, patches, and runbooks

### HOG-060 — Defender for Cloud findings (`P1`)

- Use supported assessments/recommendations/continuous export or ARG surfaces.
- Preserve resource IDs and assessment keys.

### HOG-061 — Update Manager patch context (`P1`)

- Read assessment/installation context via supported APIs/ARG/LAW.
- Update Manager remains the deployment authority.

### HOG-062 — Runbook catalog references (`P2`)

- Read metadata from approved Azure Automation, ServiceNow knowledge, or Azure DevOps repository sources.
- Graph stores links, version, approval, validation date—not copied documents.

## Epic E7 — Ontology Steward Engine

### HOG-070 — Contract validation (`P0`)

- Reject invalid endpoint types, missing provenance, invalid scores/timestamps, and forbidden fields.

### HOG-071 — Assertion reconciliation (`P1`)

- Preserve per-source assertions.
- Produce deterministic effective current view.
- Contradictions are visible and auditable.

### HOG-072 — Temporal lifecycle (`P1`)

- Grace periods and successful-observation semantics prevent false expiry.
- Incident-time graph reconstruction is possible.

### HOG-073 — Quality dashboard (`P1`)

- Coverage, freshness, ownership gaps, conflict rate, proposal age, stale edge rate, and identity errors.
- Dashboard uses Fabric/Power BI or Azure Workbooks, not a custom monitoring UI.

## Epic E8 — Fabric publication

### HOG-080 — Fabric Ontology capability spike (`P0`)

- Prove entity/relationship attributes, bindings, graph refresh, query, security, source control/deployment, and limits.
- Document any unsupported direct write/API assumptions.

### HOG-081 — Curated OneLake publication (`P1`)

- Idempotent versioned entity/edge projections.
- Atomic or recoverable publication watermark.
- Prior version can be restored.

### HOG-082 — Ontology binding and refresh (`P1`)

- Bind all v1 entities and predicates.
- Validate mandatory relationship attributes.
- Detect stale/failed graph refresh.

### HOG-083 — Agent-safe ontology view (`P1`)

- Exclude disputed/low-confidence/sensitive data by default.
- Return source/confidence/time for traversed edges.

## Epic E9 — Foundry agent integration

### HOG-090 — Azure MCP capability registry (`P0`)

- Pin/test version in each environment.
- Record native operations and gaps for all required sources.
- Prevent agent from assuming unsupported Sentinel/Defender/Update/Entra tools.

### HOG-091 — Read-only Azure MCP profile (`P1`)

- Enable only ARG, Monitor, Resource Health, and other approved read tools.
- Validate caller RBAC and auditability.

### HOG-092 — Fabric IQ tool integration (`P1`)

- Foundry agent answers graph questions through supported Fabric IQ integration.
- Tenant/workspace authorization is enforced.

### HOG-093 — Grounded response contract (`P1`)

- Answers include source links, confidence, observation timestamp, and uncertainty.
- No unsupported action claim.

### HOG-094 — Agent evaluations (`P1`)

- Golden question set covers impact, owner, dependencies, prior incident, patch, and runbook.
- Measure path correctness, citation validity, stale-data handling, overreach, and refusal behavior.

### HOG-095 — Human-approved action pattern (`P3`)

- Design only after read-only MVP passes safety review.
- Mutations use separate identity/tool boundary and explicit confirmation.

## Epic E10 — Production readiness

### HOG-100 — Scale and cost validation (`P1`)

- Validate source query costs, Fabric capacity, graph size, refresh duration, and agent budgets at representative scale.

### HOG-101 — Failure and recovery tests (`P1`)

- Source outage, throttling, partial subscription access, schema drift, bad ontology version, and stale refresh drills.

### HOG-102 — Security validation (`P0`)

- RBAC negative tests, prompt injection tests, secret/PII scanning, network validation, and audit review.

### HOG-103 — Operational readiness review (`P0`)

- SLOs, ownership, support model, escalation, runbooks, dashboards, capacity, backup/rollback, and release process approved.

### HOG-104 — Pilot and staged rollout (`P1`)

- One bounded business service and representative resource types.
- Accuracy and freshness measured against source systems and steward review.
- Expansion only after exit criteria are met.

## Suggested MVP cut

MVP includes E0–E3, HOG-040–042/044, HOG-050–053, HOG-060–061, E7, HOG-080–083, HOG-090–094, and production readiness items. Azure DevOps enrichment, mitigation learning, broad runbook catalog, and write actions follow after graph quality and safety are proven.
