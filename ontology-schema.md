# Operational Context Graph — Fabric Ontology Schema

## 1. Design intent

Fabric Ontology is the **system of context**. Azure, ServiceNow, Azure DevOps, Entra ID, Defender, Sentinel, Update Manager, and observability systems remain systems of record. AIOps publishes normalized identity and relationship assertions, not replacement inventories or telemetry.

Fabric IQ Ontology is currently preview. It supports entity types, properties, directional relationships with attributes, data bindings to supported OneLake sources, and a queryable graph. Upstream changes require graph refresh. The design therefore keeps portable canonical tables in OneLake and treats the ontology as a governed semantic projection, not as a transactional graph database.[1]

## 2. Modeling rules

- Canonical IDs are opaque, tenant-scoped, and stable.
- Source IDs remain available as aliases and deep links.
- ARM resource IDs are compared case-insensitively but preserved in source form.
- Names never establish identity by themselves.
- All relationship instances carry provenance and time.
- AI creates proposals, not authoritative facts.
- Business ownership is Team-first; Person is used only where policy permits.
- Specialized Azure entities are disjoint ontology types. `Resource` contains all Azure resources not represented by a named specialization; analytical views may union them as `AzureAsset`. This avoids duplicate graph nodes because Fabric Ontology does not provide a documented inheritance mechanism.

## 3. Common entity properties

Every entity has:

| Property | Type | Required | Meaning |
|---|---|---:|---|
| `id` | string | yes | AIOps canonical ID. |
| `tenantId` | string | yes | Entra tenant boundary. |
| `displayName` | string | yes | Approved human-readable name. |
| `sourceSystem` | string | yes | Identity authority. |
| `sourceId` | string | yes | Stable native identifier. |
| `sourceUrl` | string | no | Deep link/API locator. |
| `lifecycleState` | string | yes | `active`, `inactive`, `retired`, `deleted`, `unknown`. |
| `createdTimestamp` | datetime | yes | First creation in AIOps. |
| `lastObservedTimestamp` | datetime | yes | Latest successful source observation. |
| `schemaVersion` | string | yes | Projection contract version. |

## 4. Required entity types

### Resource

Generic Azure resource not covered by a named specialization.

Additional properties: `azureResourceId`, `resourceType`, `kind`, `location`, `subscriptionId`, `resourceGroupName`, allowlisted `tags`, `provisioningState`, `managedBy`, `environment`, `criticality`.

Authority: Azure Resource Graph (ARG).

### Subscription

Azure subscription boundary.

Properties: `subscriptionId`, `state`, `managementGroupId`, `tenantId`, `billingScopeRef`, `environmentClassification`.

Authority: Azure Resource Manager/ARG subscription context.

### ResourceGroup

Azure resource group boundary.

Properties: `azureResourceId`, `subscriptionId`, `location`, allowlisted `tags`, `provisioningState`.

Authority: ARG/ARM.

### VirtualMachine

Azure VM or VM scale-set instance when modeled individually.

Properties: `azureResourceId`, `vmId`, `vmSize`, `osType`, `powerState`, `provisioningState`, `availabilityZone`, `computerName`, `arcEnabled=false`.

Authority: ARG for inventory; Compute/Resource Health for runtime status.

### ArcMachine

Azure Arc-enabled server represented by `Microsoft.HybridCompute/machines`.

Properties: `azureResourceId`, `machineId`, `agentVersion`, `status`, `osType`, `osName`, `lastStatusChange`, `connectivityState`, `patchAssessmentMode`.

Authority: ARG and Azure Arc APIs.

### AKSCluster

Azure Kubernetes Service cluster boundary.

Properties: `azureResourceId`, `kubernetesVersion`, `fqdn`, `privateFqdn`, `provisioningState`, `nodeResourceGroup`, `identityType`, `networkPlugin`.

Authority: ARG/AKS control plane.

### Database

Managed database instance/database used by applications. This is an operational endpoint, not copied data.

Properties: `azureResourceId`, `databaseEngine`, `serverName`, `databaseName`, `fqdn`, `port`, `sku`, `highAvailabilityMode`, `environment`.

Authority: ARG and service management APIs.

### StorageAccount

Azure Storage account boundary.

Properties: `azureResourceId`, `accountName`, `primaryEndpoints`, `sku`, `kind`, `hierarchicalNamespaceEnabled`, `publicNetworkAccess`.

Authority: ARG/Storage management API. Keys and connection strings are forbidden.

### Application

Governed software service/application boundary, not a process instance.

Properties: `applicationKey`, `serviceNamespace`, `serviceName`, `environment`, `version`, `criticality`, `repositoryUrl`, `pipelineUrl`, `telemetryResourceId`.

Authorities: approved service catalog/ServiceNow; App Insights/OpenTelemetry provide observations and aliases.

### BusinessService

Business-facing or technical service delivered to customers or internal consumers.

Properties: `serviceKey`, `serviceType`, `criticality`, `serviceTier`, `slaReference`, `status`.

Authority: approved ServiceNow service portfolio or equivalent business registry.

### Team

Accountable group.

Properties: `teamKey`, `teamType`, `entraGroupId`, `serviceNowGroupId`, `azureDevOpsTeamId`, `contactReference`, `onCallReference`.

Authority: approved ownership catalog with Entra/ServiceNow/Azure DevOps aliases.

### Person

A source-referenced person only where policy permits.

Properties: `entraObjectId`, `userPrincipalNameHash` or approved UPN, `displayName`, `employmentState`, `contactReference`.

Authority: Entra ID. Minimize personal data; do not copy group membership history into the ontology unless required.

### Incident

Operational or security incident identity and concise state.

Properties: `incidentKey`, `incidentSystem`, `severity`, `status`, `classification`, `detectedTimestamp`, `resolvedTimestamp`, `summary`, `externalReferences`.

Authority: Sentinel or ServiceNow according to incident class. Full comments/evidence remain in source.

### Patch

Patch/update identity and compact state.

Properties: `patchKey`, `kbOrPackageId`, `classification`, `product`, `version`, `releaseTimestamp`, `assessmentState`, `installationState`, `rebootBehavior`.

Authority: Azure Update Manager/source package system.

### Finding

Security, reliability, cost, policy, or operational finding.

Properties: `findingKey`, `findingType`, `severity`, `status`, `category`, `firstSeenTimestamp`, `resolvedTimestamp`, `recommendationTypeId`.

Authorities: Defender for Cloud, Sentinel, Advisor, Azure Policy, or an approved quality rule.

### Runbook

Approved operational procedure/automation reference.

Properties: `runbookKey`, `runbookType`, `version`, `approvalState`, `repositoryUrl`, `executionUrl`, `lastValidatedTimestamp`, `riskClass`.

Authority: Azure Automation, ServiceNow Knowledge, or Azure DevOps repository. Content stays in source.

### RemediationPlan

Draft, evidence-backed remediation plan. It is a planning artifact, not an execution record or approval.

Properties: `planId`, `title`, `status`, `priority`, `objective`, `opportunityType`, `confidence`, `confidenceKind`, `executionAuthorized`, `executionPerformed`, `readOnly`, `environment`.

Authority: AIOps remediation planner from governed action catalog, semantic graph context, and peer intelligence outputs. Plans are proposals until human approval and execution systems accept them.

### ApprovalRequirement

Required human or process approval for a remediation plan or stage gate.

Properties: `approvalRequirementId`, `role`, `stage`, `status`, `requiredByPolicyId`, `decisionId`, `expiresTimestamp`.

Authority: Governed remediation approval policy and external approval workflow once integrated.

### ApprovalDecision

Immutable human decision recorded against a remediation recommendation. It records approval, rejection, or expiry of a recommendation; it is not an execution authorization token.

Properties: `decisionId`, `planId`, `decision`, `approver`, `decidedTimestamp`, `reason`, `scope`, `actionVersion`, `expiresTimestamp`, `revalidationStatus`, `executionAuthorized=false`, `executionPerformed=false`.

Authority: AIOps remediation decision API after server-side scope and action-version revalidation.

### ExecutionStep

Ordered proposed remediation step. It is not proof that execution occurred.

Properties: `stepId`, `stepNumber`, `description`, `stage`, `requiresApproval`, `executionStatus`, `preconditionRefs`, `successCriteriaRefs`, `failureCriteriaRefs`.

Authority: Governed remediation action catalog and remediation planner.

### RollbackPlan

Rollback or compensation strategy attached to a remediation plan.

Properties: `rollbackPlanId`, `summary`, `reversible`, `automaticRollback`, `executionStatus`, `rollbackActionRefs`, `validationRefs`.

Authority: Governed remediation action catalog and remediation planner.

### RiskAssessment

Compact risk assessment for an incident, finding, prediction, or remediation plan.

Properties: `riskAssessmentId`, `overallLevel`, `overallScore`, `drivers`, `evidenceStatus`, `assessmentTimestamp`.

Authority: AIOps risk analysis over governed evidence. It is advisory unless accepted by a downstream governance workflow.

### SimulationResult

Projected effect of a proposed action. It is scenario output, not actual post-change state.

Properties: `simulationResultId`, `riskReductionPercent`, `complianceImprovementPercent`, `lifecycleExposureReductionPercent`, `operationalDebtReductionPercent`, `downtimeRisk`, `simulationOnly`, `changesExecuted`.

Authority: AIOps remediation execution simulator from governed action-catalog effectiveness metadata.

### CostCentre

Business cost-accountability unit.

Properties: `costCentreKey`, `code`, `name`, `billingOwnerTeamId`, `budgetReference`, `activeFrom`, `activeTo`.

Authority: enterprise finance/tag governance source. Azure retail pricing is not a cost-centre authority.

## 5. Incident-learning extension entities

These are required to satisfy durable incident learning even though they were not in the minimum entity list.

### FailurePattern

A steward-approved recurring failure signature.

Properties: `patternKey`, `title`, `symptomFingerprint`, `applicableEntityTypes`, `detectionLogicRef`, `firstObserved`, `lastObserved`, `occurrenceCount`, `validationState`.

### RootCause

A normalized, reviewed causal explanation.

Properties: `rootCauseKey`, `category`, `summary`, `evidenceRef`, `verificationState`, `firstConfirmed`, `lastConfirmed`.

Do not create RootCause from an LLM summary alone. It requires an RCA/postmortem source and steward acceptance.

## 6. Relationship assertion contract

Every relationship has:

| Property | Type | Required |
|---|---|---:|
| `relationshipId` | string | yes |
| `predicate` | string | yes |
| `subjectId` | string | yes |
| `objectId` | string | yes |
| `confidence` | double `[0,1]` | yes |
| `source` | string | yes |
| `createdTimestamp` | datetime | yes |
| `lastObservedTimestamp` | datetime | yes |
| `validFrom` | datetime | no |
| `validTo` | datetime | no |
| `evidenceRef` | string | no |
| `observationCount` | integer | no |
| `assertionState` | string | yes |
| `stewardDecisionId` | string | no |
| `schemaVersion` | string | yes |

`assertionState` is one of `proposed`, `accepted`, `disputed`, `superseded`, `expired`, `rejected`.

Per-source assertions are preserved. A deterministic effective-edge view selects accepted, non-expired assertions under a versioned precedence/confidence policy.

## 7. Required relationship semantics

| Predicate | Allowed examples | Meaning |
|---|---|---|
| `belongsTo` | Azure asset → ResourceGroup; ResourceGroup → Subscription; Person → Team; asset/application → CostCentre | Administrative or governed membership. |
| `ownedBy` | asset/Application/BusinessService/Runbook/CostCentre → Team or Person | Accountable ownership, not mere creator/access. |
| `supports` | Resource/Application/Team → Application or BusinessService | Subject contributes capability to object. |
| `hosts` | VM/ArcMachine/AKSCluster/Resource → Application | Subject provides execution boundary. |
| `dependsOn` | Application/BusinessService/asset → Application or asset | Subject requires object for correct operation. |
| `calls` | Application → Application/Database/StorageAccount | Observed logical invocation. |
| `connectsTo` | asset/Application → asset | Network/session connectivity without claiming semantic dependency. |
| `impacts` | Incident/Finding/Patch/FailurePattern → asset/Application/BusinessService/Team | Subject affects object. |
| `affectedBy` | asset/Application/BusinessService → Incident/Finding/Patch/FailurePattern | Explicit inverse projection for consumer convenience. Canonical storage may derive it from `impacts`. |
| `mitigatedBy` | Incident/Finding/FailurePattern → Runbook/Patch | Risk/incident is reduced by artifact. |
| `requiresPlan` | Application → RemediationPlan | Application has an evidence-backed draft plan available for review. |
| `mitigatesRisk` | RemediationPlan → RiskAssessment | Plan is intended to reduce the assessed risk. |
| `protectsService` | RemediationPlan → BusinessService | Plan is intended to protect or improve the business service. |
| `requiresApproval` | RemediationPlan → ApprovalRequirement | Plan cannot progress without the listed approval or stage gate. |
| `hasApprovalDecision` | RemediationPlan → ApprovalDecision | Plan has an immutable human approve, reject, or expire decision record. |
| `hasStep` | RemediationPlan → ExecutionStep | Plan includes an ordered proposed execution step. |
| `hasRollbackPlan` | RemediationPlan → RollbackPlan | Plan has a rollback or compensation strategy. |
| `hasSimulation` | RemediationPlan → SimulationResult | Plan has a bounded scenario simulation result. |

### Incident-learning extension relationships

- `hasRootCause`: Incident or FailurePattern → RootCause.
- `matchesPattern`: Incident → FailurePattern.
- `documentedBy`: RootCause or FailurePattern → Runbook/source reference.

Inverse pairs such as `impacts`/`affectedBy` should have one canonical assertion and a derived inverse view to prevent conflicting double maintenance.

## 8. Identity strategy

Resolution order:

1. Exact tenant + source-native stable ID.
2. Exact ARM resource ID or Entra object ID.
3. Explicit cross-reference in an authoritative source.
4. Steward-approved alias.
5. Similarity proposal only.

Special identifiers:

- Azure assets: tenant + lower-cased ARM ID.
- Subscription: tenant + subscription ID.
- App Insights/OTel Application: governed application key; `service.namespace` + `service.name` + environment is an alias, not final identity.
- ServiceNow: instance + table/class + `sys_id`.
- Azure DevOps: organization + project/repository/team/pipeline/work-item ID.
- Sentinel: workspace ARM ID + incident resource name.

## 9. Starting confidence policy

| Evidence | Starting score |
|---|---:|
| Steward-approved | 1.00 |
| Exact native topology/identity relation | 0.98 |
| Approved ServiceNow business relation | 0.95 |
| Governed tag exact mapping | 0.85 |
| Repeated App Insights/OTel dependency | 0.75 |
| Entra/Azure DevOps organizational correlation | 0.70 |
| Incident temporal correlation | 0.55 |
| AI or name-similarity proposal | 0.30 |

Corroboration, recency, observation count, identifier quality, and contradiction adjust scores under a versioned policy. One source outage never causes decay or expiry.

## 10. Fabric physical mapping

Recommended managed OneLake tables:

- one current table per entity type;
- `relationship_assertion` for all evidence;
- one current accepted relationship table per predicate or endpoint pair if required by Fabric bindings;
- `entity_alias`, `evidence_reference`, `steward_decision`, `source_watermark`, and `publication_manifest`.

Current preview constraints include managed Lakehouse tables, one static binding per entity type, string/integer identity keys, restrictions around OneLake security/Delta column mapping, and explicit graph refresh.[1][2] Validate all constraints in a spike before production.

## 11. Quality invariants

Publication is blocked when:

- mandatory provenance is missing;
- endpoint type is invalid or unresolved;
- confidence is outside `[0,1]`;
- tenant boundaries conflict;
- timestamps are impossible;
- a forbidden secret/raw telemetry field appears;
- a self-dependency exists without an explicit approved exception.

Warnings include competing owners, stale accepted edges, dependency cycles, orphan entities, and low-confidence business mappings.

## References

[1] Microsoft, “What is ontology (preview)?,” Fabric IQ. https://learn.microsoft.com/en-us/fabric/iq/ontology/overview

[2] Microsoft, “Data binding in ontology (preview).” https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-bind-data
