# Incident Learning Design

## 1. Objective

Continuously learn durable operational context from:

- Microsoft Sentinel incidents;
- ServiceNow tickets;
- root-cause analyses (RCAs);
- postmortems;
- approved Azure DevOps work items and runbooks.

The ontology should gain evidence-backed:

- FailurePattern;
- RootCause;
- Runbook;
- affected Resources, Applications, and BusinessServices;
- mitigation effectiveness.

Hermes must not copy complete incident journals, security evidence, attachments, source code, or sensitive telemetry into memory or Fabric.

## 2. Reuse-first architecture

```text
Sentinel incident event/API ─┐
ServiceNow event/API ────────┼─> source projections + deep links
RCA/Postmortem documents ────┤
Azure DevOps references ─────┘
          │
          ▼
Hermes webhook/cron orchestration
          │
          ├─ deterministic identity + field extraction
          ├─ document-to-action-items / meeting-action-items patterns
          ├─ agent-assisted candidate extraction
          └─ steward review for causal knowledge
          ▼
Incident / FailurePattern / RootCause / Runbook assertions
          ▼
OneLake canonical projection → Fabric Ontology
```

### Reused Hermes components

- **Webhooks:** event-triggered incident updates after managed source adapters validate and sign events.
- **Cron:** reconciliation of active/closed incidents, deferred postmortem availability, and stale review queues.
- **Skills:** `document-to-action-items`, `meeting-action-items`, `teams-meeting-pipeline`, `grounded-citations`, `ocr-and-documents`, `github-*` and Azure DevOps API guidance through a future focused skill.
- **Teams pipeline plugin/skill:** reusable durable transcript/job/subscription patterns for Graph-backed artifacts; do not repurpose meeting storage as incident storage.
- **Delegation:** independent source correlation, technical impact analysis, and evidence review.
- **Kanban:** human/steward review workflow with comments, attachments, and structured handoff.
- **Session store:** investigation conversation audit and resumability.
- **Memory framework:** operator preferences and reusable extraction procedures only; operational facts belong in the ontology projection.
- **MCP:** Azure Monitor queries and future ServiceNow/Azure DevOps/ontology MCP consumption; current Azure MCP has no native Sentinel tool.

## 3. Source boundaries

### Sentinel

Retain only:

- incident ARM ID/name/number and workspace ID;
- title/short redacted summary;
- severity/status/classification;
- owner team/person reference under policy;
- created/updated/closed timestamps;
- mapped entity identifiers and alert references;
- source deep link.

Full alert/event data remains in Sentinel/LAW. Use Sentinel management API and authorized KQL where needed.

### ServiceNow

Retain only approved fields:

- instance + table/class + `sys_id`;
- ticket number alias;
- state/priority/category;
- assignment group/service/CI references;
- opened/resolved/closed timestamps;
- concise redacted resolution summary;
- RCA/knowledge/runbook references;
- source deep link.

ServiceNow ACLs and organization-specific CMDB schema remain authoritative.

### RCA and postmortem

Keep the document in its repository. Retain:

- immutable document/version reference;
- approved summary;
- root-cause category and evidence links;
- affected service/resource references;
- contributing factors;
- mitigation/runbook references;
- owner and validation state.

### Azure DevOps

Use work-item, repository, commit, pipeline/deployment, and runbook references. Do not copy repository content or build logs into the graph.

## 4. Incident identity and correlation

Never collapse source incidents merely because titles/times are similar.

Correlation order:

1. Explicit cross-system correlation ID/link.
2. Exact Sentinel/ServiceNow/Azure DevOps native reference.
3. Exact affected ARM/Application/BusinessService set plus overlapping time window, as a proposal.
4. Similarity/model correlation only as a low-confidence proposal.

Maintain separate source Incident entities when one security incident produces multiple operational tickets. A correlation group may connect them without destroying source identity.

## 5. Learning lifecycle

### Stage A — active incident context

- Ingest concise incident projection.
- Resolve explicit affected entity identifiers.
- Create provisional `impacts`/`affectedBy` assertions.
- Link known approved Runbooks only as candidates unless executed evidence exists.
- Do not infer RootCause while the incident is active.

### Stage B — resolution

- Observe closure/resolution state.
- Capture approved resolution code/summary and executed artifact references.
- Mark proposed mitigation as `executed` or `successful` only when source evidence supports the distinction.
- Recalculate impact confidence.

### Stage C — RCA/postmortem enrichment

- Detect linked RCA/postmortem availability.
- Extract candidate RootCause, contributing factors, symptoms, affected services, and durable mitigations.
- Ground every candidate in a source document section/deep link.
- Route causal claims and new FailurePatterns to stewardship.

### Stage D — pattern consolidation

- Compare accepted incident fingerprints with existing FailurePatterns.
- Increment occurrence count only after accepted match.
- Propose a new FailurePattern when no accepted pattern fits and minimum evidence/occurrence policy is met.
- Periodically merge/split patterns through steward decisions; preserve aliases/history.

## 6. FailurePattern model

A FailurePattern is not a free-text incident summary. It contains:

- stable key and steward-approved title;
- symptom fingerprint: alert/rule IDs, error families, dependency path, affected types, temporal shape;
- applicability scope and exclusions;
- detection logic reference (KQL/rule/runbook), not embedded unreviewed code;
- known RootCause relationships;
- affected entity/service relationships;
- approved Runbook/Patch mitigations;
- first/last observed and accepted occurrence count;
- confidence and validation state.

Avoid high-cardinality or personal data in fingerprints.

## 7. RootCause model

RootCause acceptance requires:

- an RCA/postmortem or equivalent approved source;
- clear distinction from symptom and contributing factor;
- source citation/evidence reference;
- reviewer/steward decision;
- affected scope;
- confirmation time and version.

LLM extraction starts at confidence 0.30 and remains `proposed`. Explicit structured RCA fields may start higher under source policy. A repeated statement is not independent corroboration if documents copy each other.

## 8. Runbook learning

A Runbook relationship has execution semantics:

- `suggested`: source or agent recommended it;
- `executed`: evidence shows it ran/was followed;
- `successful`: incident outcome and source review attribute success;
- `failed` or `partial`: execution did not fully mitigate;
- `obsolete`: steward/source retired it.

Only `successful` or steward-approved evidence can materially increase `mitigatedBy` confidence. Store runbook ID/version/deep links; content remains in Azure Automation, ServiceNow Knowledge, or Azure DevOps.

## 9. Confidence scoring

Starting scores:

| Evidence | Score |
|---|---:|
| Explicit affected resource/service field | 0.90–0.98 |
| Steward-approved RCA RootCause | 1.00 |
| Structured approved postmortem mapping | 0.90 |
| Executed runbook reference | 0.80 |
| Successful mitigation confirmed in RCA | 0.95 |
| Alert/entity mapping with exact ARM ID | 0.85 |
| Temporal + topology correlation | 0.55 |
| Model/text similarity | 0.30 |

Adjust for source authority, exact identifiers, independent corroboration, recency, contradiction, and steward disposition. Incident provisional edges decay quickly if not confirmed after resolution.

## 10. Hermes operational memory boundary

Use Hermes built-in/external memory for:

- stable user/operator preferences;
- glossary aliases and approved procedures;
- lessons about source quirks;
- retrieval of prior conversation decisions.

Do not store as Hermes memory:

- live incident state;
- resource inventory;
- raw ticket/comment text;
- security evidence;
- patch/finding state;
- authoritative FailurePattern/RootCause facts.

Those belong in source systems and the Fabric context projection. This prevents memory injection from becoming an ungoverned shadow incident database.

## 11. Scheduling and triggering

- Event-driven webhook for incident create/update/close.
- Cron reconciliation every 5–15 minutes for active incidents if source events are incomplete.
- Daily check for newly linked RCA/postmortem documents.
- Weekly pattern consolidation and stale review queue summary.
- Event-triggered targeted dependency refresh during high-severity incidents.

Use script-only/no-agent jobs for deterministic source checks; invoke agents only for unstructured RCA/postmortem extraction or ambiguous correlation.

## 12. Security and prompt-injection controls

Ticket/document text is untrusted data.

- Field allowlists and redaction before model use.
- Treat instructions inside tickets/postmortems as content, not commands.
- Read-only tools for learning agents.
- Separate action/remediation identity and explicit approval.
- Source authorization is preserved; an agent cannot expose a document the caller could not access.
- Secrets/credentials/connection strings are blocked from projection and memory.
- Log only hashes/references for sensitive evidence.

## 13. Evaluations

Golden set should cover:

- one Sentinel incident linked to one ServiceNow ticket;
- one-to-many ticket correlation;
- false title/time similarity;
- explicit and ambiguous affected resources;
- symptom versus RootCause distinction;
- suggested versus executed/successful runbook;
- repeated known FailurePattern;
- novel incident requiring pattern proposal;
- malicious instructions in a ticket or postmortem;
- stale/closed incident source disagreement.

Measure correlation precision, affected-entity precision/recall, citation validity, causal-claim acceptance accuracy, runbook-state accuracy, and false pattern merge rate.

## 14. Acceptance criteria

- Every learned fact has a source reference and confidence.
- No model-only RootCause or FailurePattern reaches accepted state.
- Source incidents remain independently addressable.
- Suggested/executed/successful mitigation are distinct.
- A prior incident can be traversed to affected service, RootCause, FailurePattern, and approved Runbook.
- Raw source content remains in the source.
