# Publication backend: source preparation only

`infra/publication-backend` is a **separate Terraform root**, not a module called
by the application stack. It has no production state, remote-state lookup,
existing-network reference or Fabric resource. Do not initialize it using an
application state file or import production resources. Default `enable=false`
creates zero resource instances; its `publication_backend_v1` output is null.
No live plan/apply is authorized by this document.

## Reviewed declaration, not execution authority

An eventual operator must explicitly supply subscription, tenant, `enable=true`,
all typed `settings` fields and a separately declared `reviewed_config_sha256`
matching `sha256(jsonencode(settings))`. The fingerprint is of Terraform's typed
object encoding, not arbitrary tfvars bytes. It detects configuration mismatch;
it is **not authenticated review, approval, sealing or runtime authority**.
The synthetic values in `tests/backend.tftest.hcl` are not deployable pins.

Settings require isolated SQL/account/container names and a name prefix for the
new RG, VNet, subnets, identity, hosting environment and scaffold Job. The explicit
Azure region code, SQL SKU/size/backup retention, storage replication and artifact
retention have no defaults. Supported initial SQL SKUs are S0/S1/S2 and
GP_Gen5_2/GP_Gen5_4; replication is Standard LRS or ZRS. Actual regional
availability, quota, pricing and SKU/size compatibility remain unqualified.

`private_connectivity` must be `isolated-vnet-private-endpoints`. An explicit
canonical RFC1918 /16 creates a dedicated /23 hosting subnet and a separate /24
endpoint subnet. DNS zones/links and Blob/SQL private endpoints are declarations,
**not proof of name resolution, route reachability or effective denial**.
CIDR non-overlap with other networks requires operator review; this root performs
no inventory. No existing ACA subnet or environment is modified. Deployment and
SQL bootstrap would need a separately reviewed private-network execution path.
Provider calls that require storage data-plane reachability must fail closed;
do not enable keys or public access to work around that requirement.

The Entra-only SQL administrator must be a separately reviewed operator group,
not the broker, worker or publisher identity (including group membership).
Terraform cannot prove group type/membership. No SQL passwords, SQL users,
procedure grants, direct DML credentials or bootstrap commands are generated.

## Unlocked draft retention and nonoperable hosting

`policy_state` supports **only `Unlocked`** in this source increment. Retention
days must be explicitly supplied as an integer in the provider/service range
1..146000. There is no approved horizon, no locked policy declaration, no lock
action and no automation to perform irreversible locking. Append exceptions are
off. GPv2 block-blob storage is non-HNS, nonversioned, private, HTTPS/TLS1.2-only,
with Shared Key authorization, public containers and local users disabled.
Account/service SAS using Shared Key are blocked; Entra user-delegation SAS is
not globally disabled by that switch. The broker receives no delegation-key,
key-list, policy-management, delete or storage write grant.

The candidate artifact role contains only container/policy reads and blob
read/write data actions. It is **unassigned**. Its assignable scope is the new RG;
the output gives the exact container ARM ID as the only proposed future
assignment scope. RBAC write itself does not distinguish create from overwrite.
Locked WORM and trusted verification would have to provide retention enforcement;
an unlocked draft and absence of delete in one role are not sufficient.
Only AcrPull on the explicit, matching ACR ID/server is assigned to the newly
created dedicated MI. No existing publisher/API/coordinator identity is reused.
Inherited grants and administrator capabilities still need independent review.

Hosting is a **NONOPERABLE Manual exit-78 ACA Job scaffold** in a new internal
environment. Its only command reports unqualification and exits 78. It has zero
retries, no event/schedule trigger, no endpoint, no protocol environment and no
SQL/storage grant. It is not a trusted service, a running broker or an invocation
transport. The reviewed digest-pinned image must support `/bin/sh`; image
qualification is not established by a schema test. Starting this scaffold cannot
exercise the protocol. Terraform does not change any current Job or caller.

## Stable preparation interface

`publication_backend_v1` uses schema `publication-backend/v1`:

| Field | Declared interface |
|---|---|
| `sql` | Server ARM ID/FQDN, database ARM ID/name; grants explicitly NONE |
| `artifacts` | Account ARM ID/name, Blob endpoint, container ARM ID/name, null version ID, versioning false, declared draft state/days, unassigned role ID/exact proposed scope |
| `broker` | New MI resource/client/principal IDs, scaffold hosting ID/kind, null endpoint |
| `connectivity` | New VNet/private-endpoint IDs, qualified false |
| Top level | Config SHA256, execution_enabled=false, qualified=false, bootstrap_required=true |

These are Terraform configuration/resource outputs, **not an object attestation,
accepted contract, immutable receipt, capability proof or discovered live pins**.
No output should be ingested as an executable backend configuration automatically.

## Separate future qualification and bootstrap

An independently authorized policy/ownership migration would be needed before
locking, including review of retention cost/irreversibility and active/rollback
horizons. `prevent_destroy` protects the proposed durable resources against
ordinary Terraform removal while their declarations remain; it is not service
immutability, backup or protection from admins/config removal. Do not externally
lock the draft and then reapply this `locked=false` root. Future locked-policy
management requires a separately reviewed source/state transition, not ignored
drift or an automatic lock toggle.

The SQL/protocol lane must separately bootstrap procedures and tables using an
operator identity over private connectivity, then grant the dedicated runtime
principal only exact procedure EXECUTE (and explicitly reviewed read interfaces).
ARM SQL Contributor/role assignment cannot grant SQL EXECUTE. Workers receive no
direct SQL DML, broad sink credentials or raw CAS endpoint. Procedure transactions
must enforce persisted authority/owner/monotonic epoch/base revision using the
DB clock and atomically update pointer, receipt and audit.

Trusted artifact sealing must read back exact account/container/blob identity,
explicit absent version ID, bytes/digest/length and enforceable retention horizon,
then persist the evidence; caller `sealed=true` is not an attestation. Readers and
restoration must pin those exact retained objects. Failed SQL commit leaves an
inactive immutable orphan; Blob and SQL do not share a distributed transaction.
Continuing Delta OVERWRITE or uploading a mutable catalog is not this architecture.
All readers, active-pointer consumers, restoration and broker transport still
require source integration and live qualification. Plan19/20 remain closed.

## Offline validation

AzureRM is pinned to **5.2.0**, matching `infra/terraform/.terraform.lock.hcl`;
the separate lock retains its platform checksums. No new provider is required.
From the repository root, offline with the installed provider mirror:

```sh
terraform -chdir=infra/publication-backend init -backend=false \
  -plugin-dir=../terraform/.terraform/providers -lockfile=readonly
terraform -chdir=infra/publication-backend validate
terraform -chdir=infra/publication-backend test
.venv/bin/python -m pytest -q tests/test_publication_backend_terraform_contract.py
```

Every test uses `mock_provider "azurerm"` and `command=plan`. These are synthetic
in-memory test plans, not plans against live state. Do not run `terraform plan`
or `terraform apply` against live state as part of this source qualification.

## Provider and service references

- [Pinned AzureRM container policy schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.2.0/website/docs/r/storage_container_immutability_policy.html.markdown):
  `locked` is supported but irreversible; this root hardcodes false.
- [Container-level WORM constraints](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-container-level-worm-policies).
- [Pinned AzureRM storage schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.2.0/website/docs/r/storage_account.html.markdown).
- [Pinned AzureRM Entra-only SQL schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.2.0/website/docs/r/mssql_server.html.markdown).
- [Pinned AzureRM ACA environment schema](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.2.0/website/docs/r/container_app_environment.html.markdown).
- [SQL object permission grants](https://learn.microsoft.com/en-us/sql/t-sql/statements/grant-object-permissions-transact-sql?view=azuresqldb-current).
- [Azure Storage permissions](https://learn.microsoft.com/en-us/azure/role-based-access-control/permissions/storage).
