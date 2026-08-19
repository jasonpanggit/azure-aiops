# Hermes Ontology Steward Design

## 1. Mission

The Ontology Steward keeps the Operational Context Graph accurate, explainable, current, and governed. It is a set of deterministic policies and workflows orchestrated by Hermes—not an autonomous LLM that silently edits operational truth.

Responsibilities:

- detect stale relationships;
- detect orphan resources;
- detect missing ownership;
- apply confidence decay;
- detect duplicates and unsafe merges;
- reconcile contradictory sources;
- validate schema and tenant boundaries;
- coordinate Fabric publication and refresh health;
- route consequential ambiguity to humans.

## 2. Reused Hermes capabilities

| Hermes capability | Steward use |
|---|---|
| Cron scheduler | Periodic deterministic quality scans, source watermark checks, decay calculations, and publication verification. |
| Cron monitor mode | Run the agent only when stable quality output changes. |
| Cron durable history/notepad | Watermarks, previous scan state, retry context; not bulk graph data. |
| Webhooks | Immediate targeted checks after source/ontology events. |
| Kanban | Human review queue with assignment, comments, attachments, review/changes lifecycle, and audit. |
| Delegation | Parallel source validation or blast-radius analysis. |
| Tool registry/plugins | Service-gated steward tools outside Hermes core. |
| MCP client | Azure/Fabric/source tools discovered at runtime. |
| Session SQLite/FTS | Investigation and decision conversation audit. |
| Built-in memory/skills | Stable policy preferences and reusable procedures—not live graph state. |
| Checkpoints | Agent/session recovery, not ontology data versioning. |
| Gateway monitoring/OTLP | Steward runtime health and redacted diagnostics. |

## 3. Steward state model

Each source assertion is immutable except for observation/lifecycle fields under a versioned policy. A separate effective-edge record points to accepted source assertions.

Steward decisions:

- `accept`;
- `reject`;
- `supersede`;
- `mergeIdentity`;
- `splitIdentity`;
- `extendExpiry`;
- `changeAuthority`;
- `quarantine`.

Every decision records actor/identity, timestamp, reason, policy version, affected assertion/entity IDs, and optional expiry. Reversal creates a new decision; history is not deleted.

## 4. Stale relationship detection

A relationship is stale when its evidence has exceeded a predicate/source-specific threshold after successful source observations.

Examples:

- runtime `calls`: short threshold based on application traffic pattern;
- observed `dependsOn`: medium threshold;
- declared `dependsOn`/`supports`: source record validity, not traffic;
- `hosts`: deployment/resource state;
- `ownedBy`: business-source update cadence;
- `mitigatedBy`: historical and generally non-decaying, but Runbook version/approval can become obsolete.

Rules:

1. Source outage or permission failure freezes staleness.
2. Dormant/batch workloads require expected-activity policy.
3. Mark `staleCandidate` before expiry.
4. Targeted source reconciliation runs before acceptance is removed.
5. Preserve historical validity interval.

## 5. Orphan detection

Types:

- **structural orphan:** Azure asset has no ResourceGroup/Subscription relationship;
- **identity orphan:** source alias cannot resolve to canonical entity;
- **business orphan:** Application has no BusinessService/support path;
- **telemetry orphan:** observed service/endpoint cannot map to Application/resource;
- **incident orphan:** affected identifier has no resolvable entity;
- **publication orphan:** relationship endpoint is absent from current bound entity tables.

Actions:

- deterministic structural orphans block publication;
- telemetry/incident orphans become review candidates with evidence;
- confirmed deleted resources remain historical, not orphan errors;
- repeated unresolved aliases create quality Findings rather than invented entities.

## 6. Missing ownership detection

Ownership coverage policy by criticality/type:

- Production BusinessService and Application: at least one accepted Team owner.
- Critical Azure assets: owner path through Application/BusinessService or direct Team owner.
- Runbook: approved Team owner and validation date.
- Person-only ownership: warning unless policy explicitly permits.
- Multiple effective accountable owners: conflict unless relationship roles are distinguished.

Evidence precedence is organization-specific but typically:

1. steward decision;
2. approved ServiceNow/service portfolio;
3. governed ownership registry/tag;
4. Entra technical owner/Azure DevOps team;
5. model/name inference proposal.

Create a Finding for missing/conflicting ownership and deep-link to remediation source. Do not become the ownership system of record.

## 7. Confidence decay

Use source/predicate policy rather than one global formula.

Inputs:

- time since last successful observation;
- expected source cadence;
- evidence type and reliability;
- observation count/windows;
- corroboration;
- contradiction;
- entity lifecycle;
- steward decision/expiry.

Conceptual policy:

- no decay before `freshFor`;
- gradual decay during `reviewAfter` period;
- transition to proposed/stale below acceptance threshold;
- expire only after targeted confirmation or explicit source removal.

Historical facts such as a confirmed incident RootCause do not decay like runtime dependencies. Their linked Runbook can become obsolete independently.

## 8. Duplicate detection

Candidate generation:

1. exact source-native ID collision;
2. exact ARM ID/Entra object ID;
3. explicit cross-reference;
4. conflicting alias reuse;
5. normalized name/FQDN/application-key similarity;
6. overlapping topology/ownership/telemetry fingerprints.

Decision policy:

- exact stable IDs auto-resolve;
- cross-source explicit references may auto-link under approved rules;
- fuzzy candidates never auto-merge consequential entities;
- cross-tenant candidates are rejected by default;
- merge stores aliases and is reversible;
- split restores prior source identities and dependent assertions.

## 9. Contradiction handling

Do not overwrite disagreement.

Examples:

- ServiceNow owner differs from Azure tag owner;
- declared dependency absent from observed telemetry;
- telemetry observes an undeclared dependency;
- Sentinel and ServiceNow disagree on incident closure;
- Update Manager says patch installed while Finding remains open.

Preserve each assertion and annotate contradiction. Effective selection uses source authority and predicate semantics. Lack of runtime observation is not contradiction unless expected activity is proven.

## 10. Schema and security validation

Block/quarantine:

- missing mandatory relationship metadata;
- invalid endpoint types;
- unresolved tenant scope;
- impossible timestamps;
- confidence outside `[0,1]`;
- forbidden secrets/raw logs/ticket payloads;
- invalid source registry entry;
- duplicate canonical key;
- unsupported Fabric physical type/name.

Run PII/secret scanning before publication and before any agent prompt receives source content.

## 11. Fabric lifecycle management

The Steward coordinates but does not bypass supported Fabric APIs:

1. validate canonical tables;
2. create immutable publication manifest;
3. project Fabric-supported physical tables;
4. apply supported ontology/binding lifecycle mechanism;
5. request/coordinate graph refresh;
6. reconcile entity/relationship counts and sample paths;
7. publish graph watermark;
8. retain rollback pointer to prior known-good version.

Current Fabric Ontology does not document a public transactional instance/schema mutation API. The “writer” publishes OneLake tables and uses supported binding/refresh operations; unsupported automation is not invented.

## 12. Scheduling

| Cadence/trigger | Check |
|---|---|
| After every source batch | Contract, identity, endpoints, forbidden fields. |
| After every Fabric refresh | Count/path/watermark reconciliation. |
| Every 15–60 minutes | Source/publication freshness, orphan endpoints. |
| Daily | Stale relationships, ownership gaps, duplicate candidates. |
| Weekly | Confidence calibration, unresolved reviews, pattern consolidation. |
| Event-driven | Resource delete/tag/owner, incident close, runbook retirement. |

Use cron monitor scripts with stable sorted output so unchanged scans suppress agent execution. Agent runs summarize only changes and ambiguous cases.

## 13. Review workflow with Kanban

Recommended task types:

- OwnershipConflict;
- IdentityMergeCandidate;
- StaleDependency;
- UnmappedTelemetryEndpoint;
- RootCauseApproval;
- FailurePatternMerge;
- FabricPublicationFailure.

A task carries only compact IDs, evidence references, confidence, source timestamps, and requested decision. Sensitive source content remains behind authorized links.

Kanban handles assignment/review/handoff. The steward decision itself is written to the governed OneLake decision table, not only a Kanban comment.

## 14. Quality metrics

- provenance completeness;
- current-source and graph freshness;
- accepted edge count by predicate/source;
- stale candidate/expired rate;
- ownership coverage by criticality;
- orphan rate by type/source;
- duplicate candidate age and merge reversal rate;
- contradiction rate;
- review queue age/SLA;
- invalid/quarantined publication records;
- confidence calibration precision by band;
- Fabric refresh latency/failure/rollback.

Expose through Fabric/Power BI or Azure Workbooks. Do not build a custom monitoring dashboard when managed views suffice.

## 15. Operational safeguards

- Discovery and steward identities are read-only to Azure sources.
- Fabric writer identity can write only designated workspace/items.
- Foundry agents consume an agent-safe accepted view.
- Mutation/remediation is a separate later capability with explicit approval.
- Azure MCP write/destructive tools are excluded from steward profile.
- Quality failures fail closed: prior graph remains active and visibly stale.

## 16. Acceptance criteria

- Every stale/expired decision is explainable by policy and successful source observations.
- No fuzzy identity merge occurs without review.
- Missing ownership creates a Finding and source-linked remediation path.
- Source contradictions remain visible.
- Fabric publication can roll back.
- Unchanged quality scans do not consume agent runs.
- Operational graph data never relies on Hermes conversation memory as authority.
