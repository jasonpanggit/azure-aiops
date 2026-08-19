# Resource Discovery Design

## 1. Objective

Continuously detect Azure resource creation, deletion, ownership changes, and tag changes while keeping Azure Resource Graph (ARG) authoritative and minimizing polling.

Hermes is the orchestration and stewardship engine. It does not become an inventory system.

## 2. Reuse-first architecture

```text
Azure Resource Notifications / Event Grid
        │ resource update/delete events
        ▼
Azure Function or Logic App validation/transform
        │ signed compact event
        ▼
Hermes webhook subscription
        │ enqueue targeted reconciliation
        ▼
Hermes agent/job + Azure MCP/direct ARG query
        ▼
Ontology Steward → OneLake projection → Fabric graph refresh

Periodic Hermes cron reconciliation ───────────────┘
```

### Reused Hermes capabilities

- **Webhook framework:** authenticated HMAC routes, event filters, route scripts, idempotency, and agent-triggered runs (`hermes webhook`; `gateway/platforms/webhook.py` and dynamic subscription support).
- **Cron scheduler:** durable jobs, retries/history, scripts, monitor mode, notepad, workdir/project context, chaining, and gateway ticker (`cron/jobs.py`, `cron/scheduler.py`, `cron/scheduler_provider.py`).
- **MCP client:** connect Azure MCP as a runtime-discovered, namespace-filtered tool surface (`tools/mcp_tool.py`).
- **Tool registry/toolsets:** service-gate Azure tools and keep them outside the core schema (`tools/registry.py`, `toolsets.py`).
- **Session/state store:** durable run audit and investigation sessions (`hermes_state*.py`, `state.db`).
- **Delegation/Kanban:** parallel subscription/source investigations and steward review work, not the high-volume event queue.
- **Gateway monitoring:** operational health export over optional OTLP.

### New capability kept minimal

- An Azure event adapter, preferably managed Azure Function/Logic App configuration rather than a new Hermes core tool.
- A standalone HOG plugin for source adapters, schema validation, watermarks, and publication. It should use generic plugin hooks and register only service-gated tools.
- Direct ARG SDK/REST adapter for arbitrary queries because current Azure MCP lacks a general-purpose ARG query tool.

## 3. Native event sources

### Primary: Azure Resource Notifications (ARN) through Event Grid

Use the `Microsoft.ResourceNotifications` system topic/event types available for resource updates and deletes at supported subscription scope. This is the preferred low-latency signal for creation, update, and deletion.[1]

Event handling rules:

- An event is a **hint**, not the canonical entity payload.
- Use the event’s resource ID, event type, event time, and event ID to trigger a targeted ARG/ARM read.
- Deduplicate by Event Grid event ID plus subject/resource ID.
- Treat delivery as at-least-once and out of order.
- When an update event arrives, compare only allowlisted material fields (tags, ownership mapping inputs, location/type/status) against the current projection.
- A delete event starts confirmation/closure; preserve history.

### Secondary: Azure Activity Log via Event Grid/Event Hub

Activity Log administrative events can identify writes/deletes and caller/change context. Use for evidence and fallback where ARN coverage is unavailable. Do not infer final resource state solely from an Activity Log event.[2]

### Service-specific events

Use only when they improve semantics:

- Azure Arc connectivity/status events where supported;
- Service Health/Resource Health events for status context;
- Update Manager assessment/install completion events or ARG changes;
- Azure Policy state-change events for governance findings.

Do not create one event pipeline per service when a resource notification plus targeted reconciliation is sufficient.

## 4. Why Hermes webhooks need an Azure adapter

Hermes dynamic webhooks expect Hermes-managed HMAC signatures and support generic route filters/scripts. Azure Event Grid has its own subscription validation and authentication semantics. Do not expose a raw unsigned public Hermes route.

Preferred order:

1. Event Grid → Azure Function/Logic App that validates the Azure event, handles subscription validation, minimizes the payload, and signs the Hermes request.
2. Event Grid → Service Bus/Event Hubs → managed receiver that signs Hermes requests, if buffering/replay is required.
3. Extend Hermes webhook as a standalone plugin only if the managed adapter proves insufficient; do not special-case Azure in gateway core.

The adapter submits only a compact trigger. Hermes then queries Azure using its own managed identity/RBAC.

## 5. Discovery flows

### Creation

1. Receive resource-updated/created hint.
2. Query ARG/ARM by exact resource ID.
3. Normalize tenant/subscription/type/ID.
4. Upsert entity observation and structural relationships.
5. Apply source mapping rules for specialized entity type.
6. Publish after schema/steward validation.

### Deletion

1. Receive delete hint.
2. Mark `pendingDeletion` with event evidence.
3. Confirm with targeted source query and/or resource-change record.
4. Close validity and set lifecycle `deleted`; retain entity/relationship history.
5. Do not cascade-delete business/incident history.

### Tag change

1. Receive update hint.
2. Query ARG current tags and, if needed, resource-change details.
3. Compare governed allowlist only.
4. Recalculate tag-derived `ownedBy`, `belongsTo CostCentre`, environment, and criticality proposals.
5. A removed tag expires only the tag-source assertion; it does not remove a higher-precedence ServiceNow/steward assertion.

### Ownership change

Ownership is multi-source and predicate-specific:

- Azure RBAC role assignments: access/administration evidence, not automatically operational owner.
- Entra application/service-principal owners: technical ownership evidence.
- governed tags: mapping evidence.
- ServiceNow service/CI owner/support group: business/operational authority where approved.

A source change emits a new assertion and supersedes the old assertion from that same source. The Ontology Steward resolves the effective owner.

## 6. Scheduled reconciliation

Events are never sufficient by themselves. Reuse Hermes cron for:

- targeted retry queue every few minutes;
- subscription incremental/resource-change reconciliation every 15–30 minutes;
- full scoped ARG reconciliation daily or at a scale-tested cadence;
- ownership and tag reconciliation daily;
- stale watermark and orphan checks hourly;
- Fabric publication/refresh verification after each accepted batch.

Cron jobs use:

- `script` for deterministic source collection/change detection;
- an agent only for ambiguity/review summaries;
- `no_agent=True` where output is a fixed watchdog message;
- durable notepad/watermark for source checkpoints;
- `workdir` to load project-specific rules;
- `context_from` only for bounded job chaining, not bulk data transfer.

Large event volume belongs in Azure Service Bus/Event Hubs, not cron notepad or conversation state.

## 7. Azure MCP reuse

Current discovered Azure MCP 3.0 beta provides:

- subscription list;
- resource group/resource listing;
- VM/VMSS/disk and AKS listing/details;
- Azure Monitor activity/log/metric queries;
- Resource Health/Service Health;
- Advisor and Azure Insights.

Use these for agent-assisted targeted investigation and operator questions. Do not use resource-group listing as cross-subscription inventory and do not use `insights get` as canonical ARG output. Use direct ARG SDK/REST for deterministic, paged, arbitrary queries.

There are no native current Azure MCP namespaces for Azure Arc machines, Defender, Sentinel, Update Manager, Cost Management, or arbitrary ARG query. These are explicit adapters/gaps, not reasons to duplicate the services.

## 8. Watermarks and idempotency

Per source/scope record:

- last event ID and event time;
- last successful targeted query;
- last successful incremental reconciliation;
- last full reconciliation;
- source query version;
- accepted observation count;
- current publication manifest and Fabric graph refresh watermark.

Rules:

- Event failure does not advance source watermark.
- A partial ARG page does not close missing resources.
- One failed run never causes deletion or confidence decay.
- Duplicate event/replay is safe.
- Schema drift quarantines the affected projection and alerts the steward.

## 9. Security

- Managed identities and least-privilege RBAC.
- Separate identities for source discovery, ontology publication, and Foundry consumption.
- Azure MCP read-only and exact namespace/tool allowlists.
- No write-capable Compute, Workbook, Monitor instrumentation, or Advisor apply tools in the discovery profile.
- Validate Event Grid origin and sign the downstream Hermes webhook.
- Store credentials in Key Vault/Hermes secret provider, never ontology or memory.
- Preserve tenant/subscription boundary on every event and query.

## 10. Failure modes and recovery

| Failure | Behavior |
|---|---|
| Missed/out-of-order event | Periodic ARG/resource-change reconciliation repairs state. |
| ARG throttling | Backoff, page, preserve prior state, retry target. |
| Event storm | Buffer in Service Bus/Event Hubs; coalesce by resource ID. |
| Source schema drift | Quarantine and steward alert; do not silently drop fields. |
| Fabric refresh failure | Keep prior graph active; mark graph stale; retry/rollback. |
| Permission loss | Report inaccessible scope separately from deleted resources. |
| Hermes gateway restart | Durable cron/state/watermarks resume; upstream buffer replays. |

## 11. Acceptance criteria

- Creation/update/delete hints reach targeted reconciliation without periodic full polling.
- Full reconciliation repairs a simulated missed event.
- Tag/owner assertion changes preserve prior provenance.
- No failed or partial scan deletes an entity.
- Every publication reports source, curated, and Fabric graph watermarks.
- No raw Activity Log/event payload is retained beyond approved evidence metadata.

## References

[1] Microsoft, “Azure Resource Notifications overview.” https://learn.microsoft.com/en-us/azure/event-grid/event-schema-resource-notifications

[2] Microsoft, “Activity Log in Azure Monitor.” https://learn.microsoft.com/en-us/azure/azure-monitor/platform/activity-log

[3] Microsoft, “Overview of Azure Resource Graph.” https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview
