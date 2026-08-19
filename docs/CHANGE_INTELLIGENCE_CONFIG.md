# Change Intelligence Configuration

```yaml
fabric:
  change_intelligence:
    enabled: true
    max_changes: 50000
    max_output_items: 100
```

`max_changes` bounds total change/deviation/incident/history evidence. `max_output_items` bounds public finding and compliance collections. Both must be positive.

`change_intelligence: false` explicitly disables the runtime. The mapping and `enabled` value are type-checked; string/list values fail closed rather than becoming truthy.

## Governed sources

Automatically consumed:

- `bronze_resources`
- `bronze_resource_changes`
- Semantic Knowledge Layer and Fabric Ontology
- Governed incident projection

Optional operator-managed Silver tables:

- `silver_policy_deviations`
- `silver_security_deviations`
- `silver_network_changes`
- `silver_identity_changes`
- `silver_iac_changes`
- `silver_expected_configurations`
- `silver_observed_configurations`
- `silver_change_history`

## Attribution

`changed_by` is projected only when the governed source supplies it. Missing attribution is returned as `Unknown`; the engine never guesses an actor. IaC pipeline/service-principal identities are treated as actor evidence, not human identities.

## Expected configuration

Expected and observed configuration tables contain canonical `target_resource_id` and governed `configuration_json`. Baselines may be populated from approved policy, deployment templates, or other authoritative configuration sources. The engine does not author or modify baselines.

Example logical baseline:

```yaml
baseline_id: NSG-PROD-001
resource_type: NetworkSecurityGroup
required_state:
  firewallOpen: false
  nsgRules: []
  requiredTags:
    environment: production
compliance_rules:
  - No unrestricted internet ingress
  - Production ownership tag required
ownership_metadata:
  owner: Network Platform
```

Change projections may additionally provide `previous_state`, `current_state`, `authorized`, and `approval_reference`. Missing authorization remains Unknown. IaC records may identify Terraform, Bicep, ARM, GitHub Actions, or Azure DevOps as their source.
