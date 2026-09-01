# Security and Governance Baseline

## Identity and access
- No resource should authenticate with shared keys or connection strings when
  a managed identity + RBAC path exists (Storage, Key Vault, Cognitive
  Services, Search, Service Bus, Event Hubs all support this).
- Role assignments at subscription or resource-group scope must use built-in
  roles wherever one satisfies the need; custom roles require a documented
  justification and periodic re-review.
- Owner and User Access Administrator should not be assigned to non-human
  (service principal / managed identity) principals except break-glass
  automation, which must be logged and alerted on when used.

## Patch and vulnerability governance
- Internet-facing VMs and container images must have no unpatched Critical or
  High CVE older than 30 days without a documented compensating control
  (WAF rule, network isolation, or approved risk acceptance).
- Patch policies must define a maintenance window and a rollback plan before
  patches are applied to production; "apply immediately with no window" is a
  policy violation for any resource with a defined SLA.

## Change management
- Any change to a production firewall/NSG rule, RBAC assignment, or Key Vault
  access policy must be traceable to an approved change record; ad hoc
  portal edits without a linked change are a governance gap.
- Infrastructure changes should flow through Infrastructure-as-Code
  (Terraform/Bicep) wherever the resource type supports it; manual portal
  drift from the IaC-declared state is itself a finding, independent of
  whether the resulting configuration happens to be otherwise compliant.

## Logging and monitoring
- Every subscription must have Activity Log and Azure Policy compliance data
  flowing to a central Log Analytics workspace with a retention of at least
  90 days for security-relevant logs.
- Diagnostic settings must be enabled on every network security group,
  firewall, and key vault; a resource missing diagnostic settings cannot be
  investigated after an incident and is treated as a monitoring gap.
- Alerts for anomalous sign-ins, privilege escalation, and mass resource
  deletion must route to an on-call channel, not just an inbox no one
  monitors.

## Data protection
- Confidential or regulated data must be encrypted at rest with
  customer-managed keys where the workload's classification requires it, and
  in transit with TLS 1.2 or higher exclusively (TLS 1.0/1.1 disabled).
- Backups for anything classified as production must have a tested restore
  procedure; an untested backup is not a control, it is an assumption.
