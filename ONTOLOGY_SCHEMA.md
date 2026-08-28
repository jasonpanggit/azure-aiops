# AIOps Operations Graph — Ontology Schema

## 1. Modeling conventions

- Entity type names are singular PascalCase; collections may be plural in user interfaces.
- Relationship names are lower camel case and read from subject to object.
- Canonical IDs are opaque strings, namespaced by tenant and type.
- Source-native IDs are retained exactly enough to deep-link and re-query the source.
- Timestamps are UTC ISO 8601.
- Confidence is a decimal in `[0.0, 1.0]`.
- Soft lifecycle state is preferred to deletion.
- No relationship may be published without `confidence`, `source`, `createdTimestamp`, and `lastObservedTimestamp`.

Fabric IQ Ontology supports entity types, properties, directional relationships, relationship attributes, identity keys, data bindings, and a queryable graph.[1] The schema below is the HOG domain contract; physical Fabric names may be shortened to satisfy preview naming limits while preserving these semantic names in documentation and metadata.

## 2. Common entity contract

Every entity type has:

| Property | Type | Required | Meaning |
|---|---|---:|---|
| `id` | string | yes | HOG canonical key. |
| `tenantId` | string | yes | Entra tenant boundary. |
| `displayName` | string | yes | Human-readable source/governed name. |
| `description` | string | no | Short, approved description; not raw ticket/log text. |
| `lifecycleState` | enum | yes | `active`, `inactive`, `retired`, `deleted`, `unknown`. |
| `sourceSystem` | string | yes | Source that established this entity identity. |
| `sourceId` | string | yes | Stable native identifier in that source. |
| `sourceUrl` | string | no | Deep link or API locator. |
| `createdTimestamp` | datetime | yes | First creation in HOG, not necessarily source creation. |
| `lastObservedTimestamp` | datetime | yes | Latest successful source observation. |
| `schemaVersion` | string | yes | Contract version used for the projection. |

Unique identity is `(tenantId, entityType, sourceSystem, sourceId)` before identity resolution. Canonical `id` may group multiple aliases only after deterministic matching or steward approval.

## 3. Entity types

### 3.1 Resource

An Azure-managed resource or approved non-Azure infrastructure item referenced by an authoritative source.

Additional properties:

- `azureResourceId` — canonical ARM ID when applicable.
- `subscriptionId`, `resourceGroup`, `resourceType`, `location`.
- `managementGroupId` — if in discovery scope.
- `kind`, `sku` — allowlisted values only.
- `tags` — selected governed tags; do not copy all tags by default.
- `provisioningState` and `availabilityState` — current projection, not monitoring history.

Primary source: ARG. Canonical ARM IDs are compared case-insensitively.

### 3.2 Application

A deployable or observable software system boundary, not every process or telemetry role instance.

Additional properties:

- `applicationKey` — governed application identifier.
- `criticality` — approved classification.
- `environment` — normalized environment.
- `serviceName` — OpenTelemetry/Application Insights logical service name when applicable.
- `repositoryUrl`, `pipelineUrl` — references only.
- `operationalStatus` — concise current status if governed.

Candidate sources: ServiceNow application/service records, Application Insights/OpenTelemetry service identity, Azure DevOps metadata, governed Azure tags.

### 3.3 BusinessService

A business-facing or technical service with an accountable owner and consumers.

Additional properties:

- `serviceKey` — authoritative service identifier.
- `serviceType` — `business`, `technical`, or governed extension.
- `criticality`, `serviceTier`.
- `slaReference` — link/reference, not a copied SLA document.
- `status`.

Primary source: the organization’s approved service portfolio, typically ServiceNow.

### 3.4 Team

An accountable operational group. Prefer teams/groups over individuals.

Additional properties:

- `teamKey`.
- `teamType` — `product`, `platform`, `operations`, `security`, or governed extension.
- `entraGroupId` — when backed by an Entra group.
- `serviceNowGroupId`, `azureDevOpsTeamId` — aliases.
- `contactReference`, `onCallReference` — links, not copied personal rosters.

### 3.5 Incident

An operational or security incident identity and concise lifecycle projection.

Additional properties:

- `incidentKey`.
- `incidentSystem` — e.g. `sentinel`, `servicenow`.
- `severity`, `status`, `classification`.
- `detectedTimestamp`, `resolvedTimestamp`.
- `parentIncidentId` — source-level parent/reference if defined.
- `summary` — redacted concise text.

Full comments, evidence, and ticket history remain in the source.

### 3.6 Finding

A security, reliability, compliance, or operational finding.

Additional properties:

- `findingKey`.
- `findingType` — `securityRecommendation`, `alert`, `vulnerability`, `policy`, `reliability`, or governed extension.
- `severity`, `status`, `category`.
- `firstSeenTimestamp`, `resolvedTimestamp`.
- `assessmentKey` or native recommendation ID.

Primary candidates: Defender for Cloud, Sentinel, Azure Policy/Advisor where approved.

### 3.7 Patch

A patch/update identity or assessed update requirement, not a custom patch deployment record.

Additional properties:

- `patchKey` — stable KB/update/package identifier in source context.
- `classification`, `product`, `version`.
- `releaseTimestamp`.
- `assessmentState`, `installationState` — projections from Update Manager/source.
- `rebootBehavior`.

Update Manager remains authoritative for assessment and deployment status.

### 3.8 Runbook

An approved operational procedure or automation reference.

Additional properties:

- `runbookKey`.
- `runbookType` — `manual`, `automation`, `pipeline`, `knowledgeArticle`.
- `version`, `approvalState`.
- `repositoryUrl`, `executionUrl`.
- `lastValidatedTimestamp`.
- `riskClass`.

Content remains in Azure Automation, Azure DevOps, ServiceNow knowledge, or the approved repository.

## 4. Relationship assertion contract

A relationship is an assertion, not an unqualified fact.

| Property | Type | Required | Meaning |
|---|---|---:|---|
| `relationshipId` | string | yes | Stable assertion key. |
| `predicate` | enum | yes | One of the six predicates. |
| `subjectId` | string | yes | Canonical subject entity. |
| `objectId` | string | yes | Canonical object entity. |
| `confidence` | double | yes | Calibrated score in `[0,1]`. |
| `source` | string | yes | Source namespace and mechanism, e.g. `arg:resourceProperty`. |
| `createdTimestamp` | datetime | yes | First time this exact source assertion was created. |
| `lastObservedTimestamp` | datetime | yes | Most recent supporting observation. |
| `validFrom` | datetime | no | Business-effective start. |
| `validTo` | datetime | no | Business-effective end; null while current. |
| `evidenceRef` | string | no | Pointer/query locator, never raw telemetry. |
| `observationCount` | integer | no | Count of aggregated supporting observations. |
| `assertionState` | enum | yes | `proposed`, `accepted`, `disputed`, `superseded`, `expired`, `rejected`. |
| `stewardDecisionId` | string | no | Audit reference for a human decision. |
| `schemaVersion` | string | yes | Contract version. |

Mandatory temporal invariant:

`createdTimestamp <= lastObservedTimestamp`, and if present `validFrom <= validTo`.

Multiple sources may assert the same triple. They remain separate source assertions. A derived effective edge selects/combines assertions under a versioned policy and carries links to all contributors.

## 5. Relationship types and allowed endpoints

### `ownedBy`

Meaning: the subject has accountable operational ownership by the object Team.

Allowed:

- Resource → Team
- Application → Team
- BusinessService → Team
- Runbook → Team

Not allowed: an individual user as the object. If the source names a person, resolve to an approved Team or retain only a source reference outside the published edge.

### `supports`

Meaning: the subject contributes service capability to the object.

Allowed:

- Resource → Application
- Application → BusinessService
- Team → BusinessService (only if organizational policy defines support responsibility)
- Runbook → Application or BusinessService (only for operational support scope)

Preferred chain: `Resource supports Application supports BusinessService`.

### `hosts`

Meaning: the subject Resource provides an execution/hosting boundary for the object Application.

Allowed:

- Resource → Application

Examples include App Service/AKS/VM/Function hosting an application boundary. A database used by an application is normally `Application dependsOn Resource`, not `hosts`.

### `dependsOn`

Meaning: subject requires object for correct operation.

Allowed:

- Resource → Resource
- Application → Resource
- Application → Application
- BusinessService → Application
- BusinessService → BusinessService

Self-loops are rejected. Cycles are permitted because real systems can be cyclic, but are flagged for review and traversal safeguards.

### `impacts`

Meaning: the subject operational condition affects the object.

Allowed:

- Incident → Resource, Application, BusinessService, or Team
- Finding → Resource, Application, or BusinessService
- Patch → Resource or Application

Direction is always condition/artifact → impacted entity. Patch impact means “this patch/update applies to or changes the target,” not “the target is already remediated.”

### `mitigatedBy`

Meaning: the subject risk/incident/finding is reduced or resolved by the object artifact.

Allowed:

- Incident → Runbook or Patch
- Finding → Runbook or Patch

A proposed mitigation remains `proposed` until execution/resolution evidence or approval exists.

## 6. Source precedence and starting confidence

These are initial policy defaults to calibrate during the pilot.

| Evidence | Starting confidence | Notes |
|---|---:|---|
| Steward-approved assertion | 1.00 | Approval has scope and expiry. |
| Exact native topology/ID link | 0.98 | Deterministic and source-authoritative. |
| Approved ServiceNow ownership/service relation | 0.95 | Subject to organizational source-of-truth policy. |
| Governed Azure tag mapped by exact rule | 0.85 | Lower if tag governance is weak. |
| Repeated App Insights/OTel dependency | 0.75 | Requires stable endpoints and evidence window. |
| Entra/ADO organizational correlation | 0.70 | Not automatically operational ownership. |
| Incident temporal correlation | 0.55 | Provisional until incident resolution. |
| AI/name-similarity proposal | 0.30 | Never auto-published as accepted. |

Adjustments:

- corroboration by independent approved source: increase under capped policy;
- stale evidence: decay by relationship/source-specific half-life;
- explicit contradiction: lower effective confidence and mark disputed;
- one failed source query: no decay and no deletion;
- successful source observation that no longer contains a formerly explicit relation: start expiry workflow.

## 7. Identity resolution

1. Exact source-native stable key.
2. Exact ARM resource ID or Entra object ID.
3. Explicit cross-reference stored by an authoritative source.
4. Governed alias approved by a steward.
5. Similarity-based match only as a proposal.

Identity merges are reversible and audited. Never merge across tenants by display name, email domain, resource name, repository name, or telemetry role name alone.

## 8. Effective graph views

- **Evidence view:** every assertion exactly as received/scored.
- **Current accepted view:** accepted, non-expired assertions above predicate threshold.
- **Proposed view:** candidate mappings for stewards.
- **Incident-time view:** graph as observed at an incident timestamp.
- **Agent-safe view:** accepted edges plus confidence/source/timestamp, with sensitive fields removed.

## 9. Data quality rules

Publication fails or quarantines records when:

- mandatory edge metadata is absent;
- endpoint does not exist or violates allowed endpoint types;
- score is outside `[0,1]`;
- source is not in the registry;
- timestamps are invalid;
- native identifiers violate tenant scope;
- relationship is a forbidden self-loop;
- PII/secrets/raw log payloads appear in allowlisted fields.

Warnings, but not always failures:

- stale last observation;
- orphaned alias;
- cycle in dependency graph;
- competing accepted owners;
- low-confidence business mapping.

## 10. Versioning and evolution

- Schema versions use semantic versioning.
- Additive optional properties are minor changes.
- Endpoint/predicate semantic changes are major changes.
- Every migration defines backward compatibility, OneLake table impact, ontology-binding impact, replay rules, and rollback.
- Preview Fabric naming/type constraints are isolated in a physical mapping document; this logical contract remains stable.

## 11. Example assertions (illustrative, not implementation payloads)

| Subject | Predicate | Object | Confidence | Source | State |
|---|---|---|---:|---|---|
| Application `payments-api` | `dependsOn` | Resource `payments-sql` | 0.82 | `appinsights:dependencySummary` | accepted |
| Application `payments-api` | `ownedBy` | Team `payments-sre` | 0.95 | `servicenow:serviceOwnership` | accepted |
| Incident `INC0012345` | `impacts` | BusinessService `checkout` | 0.70 | `servicenow:affectedService` | accepted |
| Incident `INC0012345` | `mitigatedBy` | Runbook `rollback-payments` | 0.60 | `postIncident:proposed` | proposed |

The actual records must also include all required IDs and timestamps.

## References

[1] Microsoft, “What is ontology (preview)?,” Fabric IQ. https://learn.microsoft.com/en-us/fabric/iq/ontology/overview

[2] Microsoft, “Data binding in ontology (preview).” https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-bind-data
