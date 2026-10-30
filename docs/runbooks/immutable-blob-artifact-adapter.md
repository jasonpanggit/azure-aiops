# Immutable Blob artifact adapter (source only)

`storage.immutable_blob_artifacts` implements actual `azure-storage-blob` upload,
HEAD and conditional download calls, plus authenticated **GET-only** ARM account,
Blob-service and container-policy readback. It is not a broker service, SQL
adapter, authenticated seal registry, publication endpoint or runtime permission
proof. No application, materializer, reader, CLI or Job selects it automatically.
All tests use local SDK/HTTP fakes; no live calls or grants are qualified.

## API and trusted configuration

Construct `ImmutableBlobTarget(account_id, container_name)` using server-owned,
independently reviewed configuration. The target accepts a canonical public-Azure
Storage ARM account ID and container name only. The Blob endpoint is derived from
that account, never taken from an upload request, URL, SAS, environment fallback
or caller-selected root. Sovereign clouds, custom endpoints, OneLake and HNS are
unsupported and fail closed.

`ImmutableBlobArtifactStore(target, credential)` requires a token credential.
Production composition must supply the dedicated managed identity, not a Shared
Key, SAS, publisher identity or unrestricted credential. This adapter does not
prove which principal a token credential represents or its effective permissions.
`service_client` and `management_reader` injections are **trusted composition/test
seams**, not request parameters; an untrusted replacement could fabricate evidence.
Close owned transports with `close()` after use.

1. `begin_attempt()` generates and registers a UUID namespace inside the store.
2. `upload_attempt(attempt_id, artifacts, retain_until=aware_datetime)` binds the
   complete logical-name/bytes manifest and requested horizon on first use.
3. It returns `SealedBlobInventory` only after every expected object has been
   read back and reverified, including a final full-set pass and policy read.
4. `read_object(SealedBlobObject)` revalidates exact target/name/ETag/bytes and
   current policy instead of trusting the value object's fields as authority.

Logical product names have a restricted ASCII grammar, with no slashes, escapes
or URLs. Blob names are server-derived
`attempts/<server-uuid>/<sha256(logical-name)>.blob`. A caller cannot pick an
attempt root, account or container. Attempts are process-owned: restart recovery
and any durable manifest/attempt registration belong in a separately reviewed
broker/control database. This module does not resume a caller-supplied attempt
after restart or provide a durable idempotency registry.

## Actual provider checks

Before each new object write, during each object verification, after conditional
byte readback and before returning an inventory, ARM is queried for:

| GET target | Required provider result |
|---|---|
| Exact Storage account ID | `kind=StorageV2`, explicit `isHnsEnabled=false`, `allowSharedKeyAccess=false`, `allowBlobPublicAccess=false`, exact primary Blob endpoint |
| `<account>/blobServices/default` | Explicit `isVersioningEnabled=false` |
| `<container>/immutabilityPolicies/default` | Exact policy resource ID, nonempty ETag, `state=Locked`, explicit `allowProtectedAppendWrites=false` and `allowProtectedAppendWritesAll=false`, integer creation-based retention days in 1..146000 |

Omitted, null, inaccessible, malformed or unsupported fields **reject**, not infer
safe defaults from Blob headers or a caller `qualified`/`sealed` boolean. A provider
that omits false fields is therefore unsupported until separately reviewed; this
is intentional fail-closed behavior, not a permission workaround.

All management responses require their provider HTTP Date. Their dates must be
within two minutes, and the Blob HEAD Date must agree within two minutes. No local
clock fallback qualifies an object. Dates are provider observations, **not an
atomic account/policy snapshot or a commit-time authority clock**.

An object must be an encrypted completed Block Blob, with no version ID, snapshot,
copy operation or content encoding; its exact ETag, length, creation and
modification timestamps must be coherent. The adapter computes the minimum
retention bound as provider `creation_time + locked_policy_days` (container-level
retention), not upload start time or an upload metadata assertion. That bound
must cover the explicit requested horizon, which must still be future relative
to provider dates. Current policy is rechecked after readback. Extension is
permitted; weakening or unsupported changes reject.

The immutable `SealedBlobObject` records account ARM ID/endpoint, container, exact
attempt/logical/blob names, **absent version ID**, ETag, verified SHA256/length,
creation/readback timestamps, computed retention bound and exact policy ID/ETag/
retention days. `SealedBlobInventory` records all objects, requested horizon and a
length-framed complete-manifest SHA256. These Python objects are **not signed
attestations**: a trusted broker must persist/attest the successful verification
and bind it to SQL authorization/receipt state. Deserializing or constructing one
does not establish that it came from this verifier.

## Completed create-only writes and retry behavior

Uploads specify `BlockBlob`, `overwrite=false`, `If-None-Match: *`, exact length,
transport content validation and single concurrency. The default SDK client uses
a maximum single PUT size of 4 MiB; inputs are bounded to 4 MiB per object, 1024
objects and 64 MiB total per attempt. It accepts completed bytes, not streams,
Delta log mutation, append APIs or partial block staging. Larger artifacts need
a separately reviewed bounded adapter, not silent chunking/overwrite fallback.
Zero-length completed objects are supported and verified.

Downloads use `If-Match` through `MatchConditions.IfNotModified`, exact observed
ETag and complete byte SHA256/length verification. ETag is checked again after
the read. Retries with changed manifest or horizon reject. Existing-object
conflicts are accepted only after the same full provider/byte verification.
Already verified objects retain pinned ETag/creation evidence across retries.
Ambiguous first-upload failures can leave an orphan; retry can adopt it only if
the original bound bytes and actual provider properties pass every check.

No error path deletes, overwrites, grants access, issues SAS, creates resources,
changes policy, locks retention or returns a partial/success-shaped inventory.
SDK and HTTP errors become sanitized fixed `ArtifactVerificationError` codes,
without provider URL/body/token exception chains. Objects written before failure
remain inactive orphans; there is no cleanup authority here.

## Exact additional permissions and bootstrap separation

The same default managed identity performs the ARM verification reads and Blob
operations. A separately injected verifier identity is possible only as trusted
composition with authenticated evidence handling, not a caller-declared result.
The exact required management actions are:

| ARM action | Narrow assignment scope |
|---|---|
| `Microsoft.Storage/storageAccounts/read` | Exact artifact account ARM ID |
| `Microsoft.Storage/storageAccounts/blobServices/read` | Exact artifact account's `/blobServices/default` |
| `Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read` | Exact artifact container ARM ID |

The data operations require
`Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read` and
`.../blobs/write`, assigned only at the exact artifact container. Write is not
create-only RBAC: Locked WORM enforces retention while the adapter emits
create-only requests. Workers must not hold these credentials. No delete, policy
write/lock, `listKeys`, `generateUserDelegationKey`, role management, Contributor,
account-wide Blob Contributor or SQL authority is required or provided.

**The accepted preparatory Terraform candidate role is deliberately unassigned
and lacks the account/Blob-service management reads above.** It is not sufficient
for this adapter. A separate narrow-role source/permission review is required;
this increment does not change the frozen Terraform role or assign anything.
A 403/missing read fails explicitly. Do not broaden to Contributor or infer
account configuration from data-plane headers.

Shared Key disabled blocks account/service SAS authenticated that way, not all
Entra user-delegation SAS. This adapter cannot enumerate inherited grants or prove
that no other identity can mint a delegation SAS, change versioning/configuration,
alter account ownership or delete after retention. Policy/config administrators,
credential composition, authenticated seal persistence, retention maintenance,
reader/SQL migration and commit-time authority enforcement remain separately
reviewed trust boundaries. ARM reads do not atomically fence privileged concurrent
configuration changes. SQL must still enforce persisted owner/epoch/authority
using its database clock in the commit transaction. This module neither activates
an output nor establishes overall remote publication safety or Plan19/20 clearance.

## Offline validation and official sources

The repository already installs `azure-storage-blob` through the declared
`azure-storage-file-datalake` dependency; the existing lock/qualification
environment uses Blob SDK 12.30.0. No new dependency installation or manifest
change is required for this bounded increment.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_immutable_blob_artifacts.py
.venv/bin/ruff check src/storage/immutable_blob_artifacts.py \
  tests/test_immutable_blob_artifacts.py
```

- [Container policy GET, pinned API 2025-08-01](https://learn.microsoft.com/en-us/rest/api/storagerp/blob-containers/get-immutability-policy?view=rest-storagerp-2025-08-01).
- [Blob-service GET/versioning](https://learn.microsoft.com/en-us/rest/api/storagerp/blob-services/get-service-properties?view=rest-storagerp-2025-08-01).
- [Storage account GET](https://learn.microsoft.com/en-us/rest/api/storagerp/storage-accounts/get-properties?view=rest-storagerp-2025-08-01).
- [Container-level WORM and append constraints](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-container-level-worm-policies).
- [Python Blob upload API](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.blobclient?view=azure-python#azure-storage-blob-blobclient-upload-blob).
- [Storage management/data actions](https://learn.microsoft.com/en-us/azure/role-based-access-control/permissions/storage).
