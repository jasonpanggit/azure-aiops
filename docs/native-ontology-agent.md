# Native Fabric Ontology Agent

The Connections ontology tab defaults to **Native Fabric Ontology Agent**.
Use **Ontology agent** on the configured Fabric item in **Plan** mode to
discover sources, draft relationships, validate and preview a patch. Review the
preview before choosing **Act** in Fabric. Opening the link does not invoke an
agent, submit a prompt, publish, retarget the legacy publisher or grant access.

Configure the reviewed target explicitly on the API:

```text
AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID=<workspace GUID>
AIOPS_ONTOLOGY_NATIVE_ITEM_ID=<native ontology item GUID>
```

Terraform persists only these two API environment variables through the optional
`fabric_native_ontology_target` object (default `null`, both UUIDs required).
The reviewed dev selection is
`infra/terraform/environments/dev.native-ontology.tfvars`; include
`-var-file=environments/dev.native-ontology.tfvars` when planning from
`infra/terraform`. This file selects the new-experience copy `bb479201...` in the
Ops workspace, not the legacy `191c9b47...` publisher. It does not configure any
Job, role, identity, schedule or publication target. Review the complete plan
before applying; this navigation change does not authorize unrelated drift.

The scoped `GET /api/v1/ontology-discovery/agent-capabilities` checks application
authentication and connection scope before returning this navigation metadata.
It does not read run/publication state or call Fabric or Foundry. Missing or
invalid configuration is shown explicitly; `FABRIC_ONTOLOGY_ID` is deliberately
not used as a fallback. Configured metadata is **not** a live availability,
permission, query, authoring or publication receipt.

Fabric uses the signed-in user's delegated permissions. The application's
selected connection/subscription does not constrain the external Fabric
conversation; state the intended domain and sources in the Plan request.
Conversations are browser-session scoped. Preserve reviewed results before
refreshing. Native MCP queries are a separate consumption path, not evidence
that an agent authored or published a definition.

Unattended native proposal authoring remains unavailable in this integration.
The UI never silently calls Foundry when native navigation is unavailable.
Selecting **Foundry discovery (explicit fallback)** exposes the existing durable
coordinator and publication history for that selection. Changing connection or
scope returns to native. This browser choice does not change or disable existing
deployed Job schedules; those remain separately operated and are not relabeled
as native agent execution.

The known new-experience copy uses TMDL. Do not aim a legacy JSON definition
publisher at it. A definition REST write is not a native agent execution.

## Existing exposure publication source contract

`ontology_container_image_exposure_entities` retains its existing entity IDs,
membership and generic ontology columns, including lifecycle, ontology version,
lineage, semantic metadata and the original payload. Its typed publication adds
`registry_resource_id` and `connection_id` string scalars so reviewed native
relationship plans can use an explicit registry key within connection scope.
The registry value uses the same case-folded explicit `registryResourceId` as
`silver_container_image_exposure`; missing values remain empty/unbound. It is
never inferred from an image URI, resource-ID path or a different entity.
Conflicting registry or tenant/subscription/connection mappings for the same
exposure ID fail publication rather than choosing a duplicate.

The mapper, lifecycle rebuild and candidate-derived publisher use the same
projection, including typed schemas for empty tables. Canonical `ontology_entities`
rows and other typed entity schemas are unchanged.
An overwrite with unchanged entity versions still applies an additive schema;
only a matching declared schema can use the unchanged-version skip.
This source contract alone
does not refresh a deployed table, rebind a native source, change a definition,
authorize Act or establish a relationship. A separate reviewed cloud change and
actual native Plan preview are still required before any native apply.

Supported experiences:

- [Native agent: discovery, Plan previews and reviewed Act](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-ontology-agent)
- [Ontology MCP: delegated consumption; service principals currently unsupported](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-use-ontology-mcp-server)
