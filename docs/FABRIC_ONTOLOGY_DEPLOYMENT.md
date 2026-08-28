# Fabric Ontology deployment

## Prerequisites

1. A supported Fabric capacity, workspace, and Lakehouse. The Ontology item/API is currently a Microsoft Fabric Preview capability; complete your organization's preview-feature approval before rollout.
2. Managed identity (preferred) or service principal with:
   - read/write access to the target Lakehouse and OneLake paths;
   - Fabric Contributor workspace role (or equivalent item read/write permissions) to create/update Ontology items;
   - permission to enumerate registered Lakehouse tables.
3. Azure Reader access for the existing ARG connector.
4. A pinned, preinstalled `azmcp` executable and Azure CLI.

## Configure

Copy `fabric.config.example.yaml` to a protected deployment configuration. Use immutable workspace and Lakehouse IDs in production.

For Management Group entities, also configure the existing ARG connector with accessible management-group IDs. These are queried with Azure CLI's management-group scope rather than subscription scope:

```yaml
azure:
  management_groups: ["contoso-root"]
```

```yaml
fabric:
  workspace_id: "00000000-0000-0000-0000-000000000000"
  lakehouse_id: "00000000-0000-0000-0000-000000000000"
  table_schema: "dbo"
  ontology:
    enabled: true
    ontology_id: ""
    ontology_name: "Operational_Context_Graph"
```

Leave `ontology_id` empty on first deployment. AIOps resolves an existing item by exact name or creates it. After creation, capture the immutable item ID and set `ontology_id` for deterministic production operation.

No ontology entity values or environment values require manual authoring. Entity and relationship definitions are generated from the maintained model; instances are bound to OneLake Delta tables.

The public engine contract is implemented by `ontology_manager`, `entity_builder`, `relationship_builder`, `publisher`, and `sync_validator`. Compatibility modules retain the established `ontology_publisher` and `ontology_validator` imports.

## Deploy and verify

```bash
uv run aiops-inventory fabric "Sync operational ontology" --config /secure/fabric.config.yaml
uv run aiops-inventory fabric "Show ontology health" --config /secure/fabric.config.yaml
uv run aiops-inventory ontology "Find resources with missing ownership" --config /secure/fabric.config.yaml
```

In Fabric:

1. Open the target workspace and confirm `Operational_Context_Graph` exists.
2. Confirm entity types show Lakehouse bindings.
3. Confirm relationship types show contextualization bindings.
4. Select a known VM and traverse `member_of`, `owned_by`, and reverse `hosted_on` relationships.
5. Compare entity and relationship counts with `ontology_health`.

## Definition format

The publisher uses Fabric's public-definition layout:

- `EntityTypes/{id}/definition.json`
- `EntityTypes/{id}/DataBindings/{binding-id}.json`
- `RelationshipTypes/{id}/definition.json`
- `RelationshipTypes/{id}/Contextualizations/{binding-id}.json`

Payloads are `InlineBase64`; source bindings reference the immutable workspace and Lakehouse IDs. `sourceSchema` is included only when configured.

## Verification boundary

Definition generation, REST behavior, Delta persistence, retirement, and traversal are covered locally and with mocked Fabric responses. A credentialed Fabric tenant is required to verify live Ontology creation, Lakehouse binding resolution, and tenant-specific permissions before production rollout.

References:

- [Fabric Ontology definition contract](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition)
- [Fabric REST API ontology specification](https://github.com/microsoft/fabric-rest-api-specs/tree/main/ontology)
