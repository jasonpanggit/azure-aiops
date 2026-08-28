# Validation Lakehouse Cutover

The API-triggered onboarding flow can be validated without deleting or modifying
the existing production Fabric tables. Reuse the existing Fabric workspace, but
configure a new lakehouse and ontology by name:

```yaml
fabric:
  auth:
    mode: managed_identity
  workspace_id: "<existing-workspace-id>"
  lakehouse_name: "OperationalContext_Validation"
  create_lakehouse_if_missing: true
  ontology:
    enabled: true
    ontology_name: "Operational_Context_Graph_Validation"
    ontology_id: ""
```

Set `HERMES_FABRIC_CONFIG` to this operator-managed configuration before running
the API or deploying the ACA revision. The API identity must be allowed to
resolve the workspace, create the validation lakehouse and ontology when they do
not exist, and write Fabric tables.

## Validation sequence

1. Build and push new `hermes-api` and `hermes-web` images to the existing ACR.
2. Deploy new ACA revisions with the same image tag.
3. Open the web Workbench and onboard a test subscription connection.
4. Run **Validate**, then **Sync** from the Connections page.
5. Confirm progress reaches `succeeded` and includes discovery, ontology
   publication, and Fabric table writing.
6. Verify the validation lakehouse contains the expected inventory, domain, and
   ontology tables and representative rows.
7. Run Sync a second time and confirm schemas, row counts, and content hashes
   remain stable.
8. Compare the validation output with the production baseline before scheduling
   any production cutover.

Do not run the lakehouse deletion script as part of this test. Production Fabric
items are retained for rollback and comparison.
