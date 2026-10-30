# Preparatory Blob verifier read-role follow-up

This additive increment requires the accepted separate
[`infra/publication-backend`](publication-backend-preparation.md) root. It does
not modify its original files, role or `publication_backend_v1` contract.
The three new role definitions are **UNASSIGNED**. Disabled configuration still
creates zero resources. Enabling reviewed preparation adds three role definitions,
not any assignments; the existing registry-only AcrPull assignment is unchanged.

The actual [Blob adapter](immutable-blob-artifact-adapter.md) must read account
properties and Blob-service versioning from ARM. Container headers cannot attest
to these settings. The old unassigned container candidate role does not grant
these parent-resource reads and is deliberately unchanged.

| Candidate | Single ARM action | Proposed assignment scope |
|---|---|---|
| account | `Microsoft.Storage/storageAccounts/read` | Exact new artifact account ARM ID |
| blob_service | `Microsoft.Storage/storageAccounts/blobServices/read` | Exact account `/blobServices/default` ARM ID |
| container_policy | `Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read` | Exact artifact container ARM ID |

`publication_backend_verifier_roles_v1.proposed_bindings` exposes each role
definition ID, dedicated broker principal ID, exact scope and action. Definitions
follow the existing resource-group definition/assignable-scope pattern, **not**
a proposal to assign them at resource-group scope. Each definition has precisely
one read action, empty DataActions and no exclusions. The policy-only definition
allows an independent management-read bootstrap without granting the old
candidate's Blob write DataAction.

The output always declares `assigned=false`, `execution_enabled=false` and
`qualified=false`; it is not permission evidence or authorization to create a
grant. There is no assignment switch, SQL grant, policy-write/lock capability,
key/SAS action, Contributor fallback, new worker identity or execution path.
Any future grant needs separately reviewed exact principal/scope and effective
inherited access evidence. Control-plane role definitions alone neither authorize
Blob uploads nor enforce SQL stored-procedure EXECUTE permissions.

This remains preparation: the Unlocked draft policy and Manual exit-78 scaffold
are NONOPERABLE and unqualified. ARM authorization at these proposed resource
scopes, private reachability, inherited grants, token behavior and real provider
responses have **not** been exercised. Missing read permissions must fail closed
in the adapter; never infer settings or fall back to broader roles.

Offline checks use the repository-pinned AzureRM 5.2.0 schema and mock-only
Terraform plans. Do not plan against live state or apply as part of this increment.

Official references:

- [Storage ARM actions](https://learn.microsoft.com/azure/role-based-access-control/permissions/storage)
- [Custom role scope and permissions](https://learn.microsoft.com/azure/role-based-access-control/custom-roles)
- [Azure RBAC scope](https://learn.microsoft.com/azure/role-based-access-control/scope-overview)
