# Publication-specific review authority

`PublicationAuthorityIssuer` is an explicit, inert operator composition, not a
broker route or a default runtime feature. It bridges independently signed
publication review to the existing `SqlPublicationAuthority.record_grant` client.
It does not sign reviews, select trusted operators, provision identities, lock
retention, acquire sessions, publish artifacts, or commit a publication.

## Released-source compatibility and dependency boundary

This source handoff is based on released commit
`ee7dcceccb7952e6405a8312d3f2875c60d80c63`, not the earlier isolated broker
assembly. That release has the maintenance reader and Key Vault transport but
does not contain `sql_publication_control.py`. This handoff explicitly includes
that SQL client, its `schema.sql` and `permissions.sql` resources, offline driver
regressions and wheel resource inclusion. It does not replace the released
maintenance module or change its acceptance logic.

The adapter consumes that released module's existing canonicalization,
signature, trust and live-reader contracts. SQL `SessionDeadline` is the known
UTC `datetime2` provider field and may omit a timezone in SQL JSON; the adapter
normalizes only this field. Signed review timestamps still require an explicit
timezone. Offline tests exercise the combined released source, not a maintenance
module substituted into the earlier broker assembly.

Including SQL scripts does not execute them or change existing database objects.
`bootstrap_database` remains an explicit administrator operation and is not
called by the authority adapter. Do not execute packaged schema/permission
scripts against an existing commissioned database merely to integrate this
source. Importing the module, installing a wheel or supplying trust configuration
does not provision an authority job, grant rights or issue an `AuthorityGrant`.
The separately scoped runtime composition and live commissioning remain gated
by the operator inputs below.

## Required operator inputs

Supply server-owned live `TrustContext` and `MaintenanceReleaseReader` using the
existing maintenance trust/attestation verification. The released reader supports
exactly one local public-config file or version-pinned Key Vault secret loaded by
an explicit user-assigned Managed Identity. Preserve that released loader; do not
copy an older local-only implementation over it.

The config needs an operator-selected `release_attestor` issuer and independent
`ontology_steward`, `security_owner`, and `fabric_governance_steward` approvers.
Provide their actual public Ed25519 keys, key IDs and role/identity bindings.
Each approval must use a distinct identity and public key, separate from the
issuer. No private key belongs in runtime trust configuration or this repository.
Managed Identity can retrieve configured trust; it cannot select or approve it.
Do not use the test fixture identities or keys as runtime trust.

The adapter also needs a server-owned review source, fresh revocation source,
exact target UUID and six-field ontology tuple, a control reader and a **separate
authority SQL client**. Do not attach authority credentials to the worker or
broker. The adapter installs no credentials, grants or listeners.

## Signed review contract

The envelope contains exactly `algorithm` (`Ed25519`), `key_id`, `payload` and
base64 `signature`. Canonical signing bytes and approval messages reuse
`maintenance_release.canonical_json` and `approval_message`. The payload has:

- `version`: `publication-authority-review/v1`.
- `environment`, `implementation_digest`, `identity_digest`, `template_digest`,
  `root_capability_digest`: exact live trust pins.
- `issuer`: exact `issuer_id`, `key_id`, `role` (`release_attestor`).
- `target_id` and `target`: reviewed UUID and the exact six-field ontology tuple.
- `owner_id`, `session_id`, positive integer `epoch`, and `attempt_id`.
- `catalog_digest` and `evidence_digest`: lowercase 64-character SHA256 hex.
- `operation`: exactly `admit` or `restore`, independently approved.
- `release_binding`: exact current verified maintenance authorization binding.
- `issued_at`, `valid_from`, `valid_until`: timezone-aware timestamps.
- `revocation_revision` and `approvals`.

Each approval contains exactly `role`, `approver_id`, `key_id`, nonempty `reason`,
`expires_at`, and `signature`. Its signature covers the existing
`approval_message` format using the digest of the payload without `approvals`.
The issuer then signs the entire payload including approvals.

The evidence digest must identify the actual protected reviewed evidence. An
arbitrary digest is not evidence; real trusted reviewers must independently
evaluate and sign the exact catalog, session, operation and evidence binding.
This module verifies those signatures, not the truth of an unsigned assertion.
The existing maintenance verifier still requires its complete prerequisite,
evaluation and live evidence floors; this adapter cannot waive them.

## Fresh validation and SQL boundary

`validate(operation)` performs the complete signed-review and live-provider
checks below but never invokes the authority client. It returns only the
signed-envelope digest for operator diagnostics. It does not create a grant,
reserve a session or produce a reusable authorization token. `issue(operation)`
always repeats all checks from fresh sources; a previously successful validation
cannot bypass later expiry, revocation, review changes or session changes.
Read-only validation still requires actual operator trust, live release evidence
and a sealed retained catalog. Missing inputs fail closed rather than producing
a success-shaped readiness result. This method does not manufacture missing
provenance or turn offline fixture evidence into live authorization.

`issue(operation)` reads the server-selected review, verifies all signatures,
deployment pins, operation, freshness, target and approvals. It requires a fresh
revocation snapshot with exactly `kill`, integer `revocation_revision`,
`revoked_key_ids`, and `revoked_reviews` (signed-envelope digests).

It re-verifies the inherited live release, reads the actual current SQL
owner/session/epoch/deadline, and reads the sealed unexpired attempt through the
existing control client. The actual catalog bytes must hash to the signed
digest. Review validity cannot exceed either the session or release expiry.
Release, session, revocation and time are checked again after provider callbacks.
Then exactly one `RecordGrant` is dispatched, with the signed-envelope digest as
authority digest. SQL serializes the authoritative session/revocation check and
the grant/audit insert. The adapter does not automatically retry uncertain writes.

Fresh review revocation prevents future issuance; it does not erase a previously
recorded SQL grant. The authority operator must dispatch the existing
`SqlPublicationAuthority.revoke` operation for an issued binding; SQL commit
checks that authoritative revocation atomically. Do not claim a local revocation
file alone invalidates already-issued SQL grants.

## SQL connection identity isolation

The live permission proof exposed cross-identity ODBC session reuse with the
same DSN and access tokens supplied through `attrs_before`. Correct token claims
do not establish the identity of a pooled SQL session. The v3 SQL client must
not be activated; this replacement requires both startup pooling configuration
and a server-observed identity assertion on every native connection.

The operator-composed job must set `pyodbc.pooling = False` **before the first
ODBC connection in the process**, including connections from other modules.
The SQL client refuses native connections while pooling is enabled; it does not
silently change global driver state or claim that a late assignment clears an
existing pool. A fresh process is required after correcting startup ordering.

Construct each native SQL client with the explicit operator-selected
`expected_client_id`. For the commissioned DEV identities, the authority pin is
`dafc75c0-45b5-4b6a-b761-da231fb6239d` and the separate reader pin is
`ad01e219-c3f5-40c7-85c3-7060a86a5bd7`. These are client IDs, not principal IDs
or signer identities. Use separate explicit MI credentials; do not infer pins
from an unverified token or from whichever credential happens to resolve.

Before any publication procedure, the client queries its current contained
database principal through `sys.database_principals` and compares its client-ID
SID and `DB_NAME()` against those independent pins. Missing, malformed or
different identity results close the connection and refuse the operation.
Deferred query failures are drained and sanitized through the existing provider
error boundary. Identity checks use the configured statement timeout. A late
pooling flag change cannot bypass this server identity check.

The existing injected `connect` seam remains for offline tests and explicitly
operator-owned connection factories. Supply `expected_client_id` there too for
the same check; an unpinned injected factory is not a qualified production
connection boundary. Neither factory injection nor a test pass authorizes
runtime activation.

Offline regressions model sequential authority/reader checkouts on the same
DSN, wrong-session reuse, incorrect database/SID, deferred failures and cleanup.
They do not reproduce the native driver's pool. Before activation, a separately
authorized manual job must run this exact replacement code in a fresh process,
verify server-observed SQL identity for both MIs in repeated/interleaved
connections, and exercise read-only refusal/success paths. Do not invoke
`RecordGrant` or `Revoke` just to prove permissions. The prior pool-disabled
diagnostic receipt is permission evidence, not proof this replacement is live.

## Exact access handoff; no automatic deployment

An authority container job needs only its separately reviewed user-assigned MI,
item Read on the dedicated SQLDatabase, and object EXECUTE on `RecordGrant` and
`[Revoke]`, with direct publication-schema SELECT/DML denied. Do not grant a
workspace role, schema-wide EXECUTE or directory role. A separately scoped
control reader performs the existing read procedures; authority does not imply
control or verifier membership.

If Key Vault transport is selected, specify the exact existing vault resource
ID, secret name/version URI, job MI principal/client IDs and narrow secret-get
permission before an access write. Do not guess missing IDs, secret versions or
assign a vault-wide broad role as a shortcut. Verify actual MI retrieval from the
private job network and the returned public-config shape without logging values.

Retention policy/lock is a separate storage operation and remains outside this
adapter. No WORM or authority qualification follows from an offline test pass.
Use the existing commissioning recipe's exact policy/ETag, retention horizon,
payload budget and irreversible-action gates. Production cutover stays separate.
