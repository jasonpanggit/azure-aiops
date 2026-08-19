# Hermes Operations Graph — Microsoft Fabric Integration

## 1. Role of Fabric

Microsoft Fabric is the governed semantic and analytics plane for Hermes Operations Graph (HOG), not the source of operational truth. The integration uses:

- **OneLake/Lakehouse managed tables** for compact canonical graph projections and assertion history.
- **Fabric IQ Ontology (preview)** for enterprise vocabulary, entity/relationship definitions, data bindings, graph construction, and business-level query.[1]
- **Graph in Microsoft Fabric** as the ontology instance-graph capability exposed through the Ontology experience.[1]
- **Fabric data/Fabric IQ integration with Microsoft Foundry** for agent consumption.[2]
- **Ontology MCP endpoint (preview)** as an optional external-agent consumption surface, separate from Azure MCP Server and not a write API.[6]
- **Power BI/Fabric experiences** for quality, coverage, stewardship, and operational views.

Raw metrics, logs, traces, alerts, CMDB records, incident journals, and directory dumps stay in their authoritative systems.

## 2. Current capability and status

As of the architecture discovery date, Fabric IQ Ontology is a **preview** feature.[1] Microsoft documents:

- entity types, instances, properties, directional relationships, relationship attributes, and cardinality;
- identity keys and data bindings to OneLake sources;
- static and time-series bindings from supported Lakehouse/Eventhouse data;
- a queryable graph with provenance and source lineage;
- business-level traversal and natural-language-to-ontology query;
- Foundry agent connectivity through Fabric IQ.[1][2]

Preview status is a material production risk. The implementation plan therefore makes Fabric capability validation a gate and keeps canonical tables portable.

## 3. Integration pattern

```text
Azure/enterprise authoritative systems
        │ native query/API/connector
        ▼
Discovery engines (compact observations/assertions only)
        ▼
Ontology Steward Engine
        │ accepted + proposed + evidence references
        ▼
Versioned managed Lakehouse tables in OneLake
        │ ontology data bindings
        ▼
Fabric IQ Ontology / Graph in Microsoft Fabric
        ├── governed graph exploration and analytics
        ├── data/Fabric agents
        └── Microsoft Foundry Agent Service
```

This is a **semantic publication pattern**, not a second monitoring or CMDB platform.

## 4. Canonical OneLake model

Recommended logical projections:

| Projection | Purpose |
|---|---|
| `entity_current` | Current compact common entity properties. |
| one table per entity type | Fabric-friendly type-specific properties and identity key. |
| `relationship_assertion` | Per-source assertion history and all mandatory edge metadata. |
| one table per predicate or endpoint pair | Fabric-friendly relationship binding if required by preview constraints. |
| `effective_relationship_current` | Policy-selected accepted current edges. |
| `entity_alias` | Source-native ID to canonical ID mappings. |
| `evidence_reference` | Query/source locator and aggregate window, never raw telemetry. |
| `steward_decision` | Approval/rejection/supersession audit. |
| `source_run_watermark` | Source freshness and successful-observation status. |
| `publication_manifest` | Schema/data version, counts, hash references, and graph refresh state. |

Physical layout must be validated against current Ontology binding constraints. Logical contracts remain independent of the preview’s naming and type limitations.

## 5. Fabric Ontology Writer responsibilities

The required “Fabric Ontology Writer” is an adapter with four responsibilities:

1. **Project:** transform accepted logical records into Fabric-supported physical tables/types.
2. **Publish:** write idempotent versioned managed Lakehouse projections and a publication manifest.
3. **Bind/configure:** maintain supported Ontology entity, property, relationship, and source bindings through documented Fabric mechanisms.
4. **Refresh/verify:** request or coordinate supported graph refresh, verify counts/paths/watermarks, and expose stale/failed status.

It does not assume a general-purpose Ontology instance-write API. Microsoft’s documented model binds ontology definitions to data in OneLake and builds the instance graph from those bindings.[1][3]. Ontology item lifecycle and public definitions are automated through the documented `/ontologies`, `getDefinition`, and `updateDefinition` Fabric REST APIs; instance data remains in bound Lakehouse tables.

## 6. Entity and relationship mapping

### Entity keys

Each bound entity type uses a tenant-scoped canonical `id` as its identity key. Source IDs are properties/aliases. This avoids name collisions and permits reversible identity resolution.

### Relationship instances

Each accepted relationship carries:

- `relationshipId`;
- subject and object canonical keys;
- `confidence`;
- `source`;
- `createdTimestamp`;
- `lastObservedTimestamp`;
- state and optional validity/evidence fields.

Fabric documentation states that relationships can carry attributes, which is the required fit for HOG provenance metadata.[1] The capability spike must verify that all four mandatory attributes are preserved and queryable on bound relationship instances at target scale.

### Views

- **Evidence:** all per-source assertions.
- **Current accepted:** non-expired accepted edges above predicate threshold.
- **Proposed:** review candidates, isolated from default agent queries.
- **Incident-time:** temporal reconstruction by validity/observation fields.
- **Agent-safe:** approved fields and accepted edges with provenance.

Whether each is a separate Ontology binding, Lakehouse view/table, or query pattern is decided by the spike and current Fabric support.

## 7. Binding and refresh constraints

Microsoft currently documents important preview constraints for Ontology data binding:[3]

- static data must be available through supported OneLake-backed sources;
- Lakehouse bindings require managed tables;
- Lakehouses with OneLake security enabled are not supported as binding sources in the documented preview behavior;
- Delta column mapping is not supported for the ontology graph;
- an entity type supports one static binding, though it can have multiple time-series bindings;
- supported identity-key types are currently limited to string and integer;
- upstream data changes require graph-model refresh before they appear in the Ontology experience.[1][3]

Architecture consequences:

1. Use a dedicated curated Lakehouse/workspace boundary with only approved graph projections.
2. Avoid special-character/column-mapping dependencies in physical names.
3. Join/enrich multiple source assertions before the single static entity binding, while retaining per-source assertion rows.
4. Treat OneLake and Ontology/graph refresh as separate watermarks.
5. Never report an ontology answer as current when the source or graph watermark is stale.
6. Reassess security design if preview binding constraints conflict with required OneLake security controls; do not weaken controls silently.

## 8. Real-time and time-series strategy

HOG does not stream all operational telemetry into Fabric. The default pattern is:

- raw telemetry remains in Azure Monitor/LAW/App Insights;
- discovery queries produce compact dependency or health evidence windows;
- accepted graph assertions publish on a controlled cadence;
- Eventhouse/time-series bindings are used only when a justified operational scenario requires contextual time-series data and security/cost controls are approved.

Fabric Ontology can bind time-series data after static identity is established, but upstream changes still require refresh for the graph representation under the documented preview behavior.[1][3] “Real-time” must therefore be stated per layer: source event time, curated publication time, and ontology graph refresh time.

## 9. Foundry and agent consumption

Microsoft Foundry Agent Service can connect to Fabric IQ as a tool so agents reason over ontology-grounded enterprise context.[2] Recommended split:

- **Fabric IQ tool:** graph traversal, business vocabulary, entity/relationship reasoning.
- **Azure MCP Server:** approved live Azure Monitor, resource listing/insights, Resource Health, and other validated tools, configured read-only.
- **Direct approved connector/tool:** arbitrary ARG plus Sentinel, Defender, Update Manager, Entra, ServiceNow, or Azure DevOps when no validated native Azure MCP tool exists.

Fabric also documents a preview MCP endpoint for an ontology.[6] Treat it as an alternative consumption adapter when a client cannot use the native Foundry Fabric IQ tool. It requires authorization to the underlying Fabric workspace/items and qualifying Fabric/Power BI capacity; it does not provide a documented ontology schema/instance mutation API.[6]

Agent responses must return the graph path and edge metadata, and distinguish ontology freshness from live-source checks. Foundry must not be used to bypass Fabric/source authorization.

## 10. Security and governance

- Isolate dev/test/prod workspaces and capacities as required.
- Use Fabric workspace roles and least-privilege service principals/managed identities where supported.
- Apply tenant settings only to approved security groups.
- Restrict the publication identity to designated curated items.
- Apply sensitivity labels, Purview controls, lineage, audit, and deployment approvals.
- Keep personal ownership data minimized; publish Teams, not individual rosters.
- Keep disputed/proposed edges outside the default agent-safe view.
- Validate whether each consuming experience enforces source/workspace permissions as expected.

Ontology preview requires explicit Fabric tenant settings.[4] Enable them only for scoped groups during the pilot.

## 11. ALM, versioning, and rollback

Required release unit:

- logical ontology version;
- physical Fabric mapping version;
- curated data publication version;
- Ontology item/configuration version;
- source query/policy versions;
- validation report.

Release sequence:

1. Validate schema compatibility in dev.
2. Publish new versioned projections.
3. Apply supported Ontology lifecycle/deployment mechanism.
4. Refresh graph.
5. Reconcile counts, mandatory attributes, sample paths, and authorization.
6. Advance the production publication pointer only after validation.

Rollback restores the prior projection and ontology mapping together. Do not depend on manually editing production ontology as the only recovery method.

## 12. Capability spike checklist

The spike must answer with evidence:

- Can all eight entity types and six predicates be modeled?
- Are relationship attributes queryable and preserved at instance level?
- Can one canonical entity incorporate multi-source aliases while using one static binding?
- What are current table/row/property/relationship/graph limits?
- What refresh APIs/schedules and latency are available?
- Are Ontology items supported in Fabric Git integration/deployment pipelines/REST APIs?
- What service-principal and managed-identity operations are supported?
- How do workspace, OneLake, and source permissions interact for consumers?
- How are schema changes, deletes, and relationship expiry represented?
- Can Foundry retrieve source/confidence/timestamp reliably?
- Does target region/capacity support all required preview features?

A failed mandatory item triggers an architecture review, not an unsupported workaround.

## 13. Acceptance criteria

- Canonical source projections remain independently queryable/exportable without Ontology.
- Fabric binds all required entities and predicates.
- Every accepted edge exposes all four mandatory metadata fields.
- Entity/edge counts and selected paths reconcile with curated tables.
- Source, publication, and graph watermarks are visible.
- Preview constraints and operational manual steps are documented.
- Security controls are not weakened to satisfy preview limitations without explicit risk acceptance.
- Foundry answers are grounded in authorized, current-enough graph data.
- Rollback to a prior known-good graph version is tested.

## References

[1] Microsoft, “What is ontology (preview)?,” Fabric IQ. https://learn.microsoft.com/en-us/fabric/iq/ontology/overview

[2] Microsoft, “Connect agents to Microsoft Fabric with Fabric IQ (preview).” https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq

[3] Microsoft, “Data binding in ontology (preview).” https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-bind-data

[4] Microsoft, “Ontology (preview) required tenant settings.” https://learn.microsoft.com/en-us/fabric/iq/ontology/overview-tenant-settings

[5] Microsoft, “Generating an ontology (preview) from a semantic model.” https://learn.microsoft.com/en-us/fabric/iq/ontology/concepts-generate

[6] Microsoft, “Use ontology as an MCP server (preview).” https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-ontology-mcp-server
