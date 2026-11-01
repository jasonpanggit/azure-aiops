# Immutable attempt publication — source core, authority none

This default-off increment implements the immutable-attempt protocol core and
explicit migration points. It does **not** make current OneLake overwrite
sinks safe, enable a broker, or qualify remote publication. The accepted
fixed-table/local-manifest path remains the default and its restrictions remain.

## Implemented source path

`CandidateGenerationMaterializer(publication_protocol="immutable-attempt/v1",
attempt_boundary=..., output_policies=(...))` selects the new path explicitly.
It requires the existing reviewed complete projection policy and verifies the
immutable staged candidate, fresh existing admission authorization, exact
six-field target, source type/triple closure and complete product projection.
It creates finished canonical JSON product snapshots with Arrow schema
fingerprints, not live mutable Delta logs. The projection policy's fixed URIs
remain a projection check, **not** the destinations used for attempt writes.
Current materializer composition still requires a local projection writer;
no remote runtime composition is enabled.

`bind_attempt` accepts a session issued by an enforcing boundary. Calling the
materializer writes only its private immutable attempt and complete catalog.
`commit_attempt` rechecks the staged binding and admission authorization, then
requests one guarded commit of the exact attempt. Caller-side checks do not
replace authoritative commit-time checks. No generic raw CAS or grant update
is exposed through `ImmutableAttemptProtocol`.

The boundary issues exact object identities after creating/verifying bytes:
account resource ID, endpoint, container, exact object name, length, content
digest and observed ETag. `version_id` is explicitly absent in this baseline.
Every descriptor is bound into the complete catalog digest. Storage mapping
belongs to the broker; callers supply logical product names, not storage URLs.
Catalog physical identity, protection horizon, full inventory and verification
evidence must be persisted by the enforcing adapter's seal operation.

The existing `PinnedProductReader` selects the boundary's combined active
reference and exact sealed catalog, never `ProductReceiptStore.latest`, latest
Delta heads, fixed table URIs or a legacy OneLake pointer. A receipt contains
the exact attempt/catalog reference. Reads verify exact product content,
length, row count and Arrow schema fingerprint. An unpublished later attempt
with the same generation cannot change the active reader.

`restore_attempt` validates the retained staged binding, separately calls the
existing `authorize_restore`, and requests an independently authorized guarded
control transition to the exact retained catalog. Restoration never rewrites
retained/current products. Admission authority is not restore authority.

Legacy materializer bind/CAS/recovery methods and
`OntologyGenerationPublisher.publish` explicitly refuse the attempt protocol.
This prevents a second legacy pointer being mistaken for the combined active
control. The existing worker/consumer lifecycle is **not** enabled for it.
Callers must use the explicit attempt methods; full governed lifecycle,
five-consumer convergence and operational recovery remain unqualified.

## Enforcing boundary — cannot be replaced by raw CAS

`AttemptBoundary` is a trusted storage/authority adapter contract, not a feature
boolean. It owns private namespaces, write-once product/catalog storage,
server-verified seals and the combined owner/epoch/active revision. It must
serialize authoritative admission/restoration grants, revocation, takeover,
deadline checks and pointer/receipt/audit/idempotency at the guarded transition.
Unchanged owner text does not reset epoch or permit ABA. Repeating an exact
request recovers its historical result; it never reapplies a stale pointer.
Changed request fields reject.

Outcome recovery is a separate **read-only**, authenticated boundary operation.
The core calls `recover_commit` before catalog/retention reads. An exact recorded
outcome returns even after expiry, revocation or takeover; it is historical,
not the current active pointer and not artifact-read authorization. An absent
outcome still requires every fresh catalog and commit-time authority check.
Lookup/transport errors propagate, never become "not found." The commit boundary
also checks idempotency inside its serialized transition to close concurrent
retry races.

The actual materializer remembers the exact authorization digest **before**
calling commit, so a lost response can be recovered before reauthorization.
This cache is not authority and is not durable. After application restart,
`recover_attempt_outcome` accepts the durably saved original session, reference,
base revision, operation, request ID and authorization digest; it cannot start
a new commit. `commit_attempt`/`restore_attempt` can also receive the original
`authorization_digest` explicitly for retry, but a missing outcome still runs
all fresh checks and requires the digest to match that fresh authorization.
No current-state or latest-receipt lookup substitutes for original request pins.

Legacy guards inspect a bound method's owning object as well as the callable.
Opaque wrappers cannot be classified before invocation; returned attempt
protocol tags or an `attempt_reference` are rejected before any legacy pointer
CAS. Ordinary untagged fixed-table callbacks retain their existing behavior.

`OneLakeAttemptBoundary` and `AzureSqlBlobAttemptBoundary` both **always refuse**.
No production SQL procedures, Blob SDK upload, broker transport, authority
migration, infrastructure or provider qualification are implemented. The latter
is a reserved unavailable composition, not a fake successful provider adapter.
Passing `qualified=True`/`immutable=True`, raw OneLake CAS or broad credentials
cannot enable this protocol.

Unified's proposed provider option (not provisioned/authorized here) requires:

- Dedicated broker MI, not the shared production publisher UAI. Workers get no
  SQL, Blob, SAS or protected-OneLake mutation credentials. Trusted broker maps
  authenticated caller identity to server-owned target/session.
- Azure SQL **control database**, not a Lakehouse analytics endpoint. Broker
  has only closed procedure EXECUTE permissions, no direct DML/DDL. SQL owns
  revocation ordering; stale copied OneLake flags are insufficient.
- GPv2 block blobs, container WORM **Locked**, versioning verified disabled,
  no append exceptions, exact inventory/readback and sufficient effective
  retention for every active/retained object. Unlocked, expired, unknown,
  inadequate or merely pending retention fails. Workers cannot supply seal
  booleans. Broker has no runtime delete/policy/key/SAS/role administration.
- Trusted verifier persists sealed object inventory/digests/lengths/ETags,
  account/container identity and protection horizon. SQL commit checks this
  record and DB-side authority/epoch/base revision/horizon under shared locks,
  then atomically commits pointer, receipt, audit and idempotent result.

There is **no** SQL/Blob distributed transaction. A rejected commit leaves an
immutable unreachable orphan. A lost commit response is resolved by the exact
idempotency record. A missing/corrupt/unprotected artifact fails reads closed.
Retention expiry is not garbage-collection permission.

Deadline semantics for that proposed adapter linearize at the final guarded
DB state transition, not network acknowledgement or durable-commit completion
before expiry. If current policy requires a stronger deadline, the adapter
must remain unsupported until that decision is resolved; this source does not
silently redefine existing authority semantics.

## Evidence and limits

`tests/test_immutable_attempt_protocol.py` supplies a trusted **test-only**
broker: a serialized authority boundary, private immutable fake artifact
service and real local `OneLakeDocumentStore` CAS for combined control. Its
mutex models one control transaction, not a distributed lock. Its simulated
retention inspection is not Azure policy evidence. It persists pointer,
receipt, audit and idempotency outcome together; simulated broker restart
retains the independent artifact service and control store.

Tests exercise actual materializer/reader/restoration methods as well as the
core: paused stale A/B takeover, learned-current-revision bypass denial,
latest-receipt confusion, retained overwrite denial, expiry/revocation gaps,
independent restoration, ABA, partial catalog visibility, upload and response
loss, exact retries, replay after takeover and retention refusal. No cloud
resource is contacted and no test fixture is an accepted live binding.

This proves core behavior conditional on the boundary, not remote enforcement.
Remaining provider work is the dedicated broker/procedure-only SQL adapter,
authoritative grant migration, locked WORM verifier/uploader, actual identity
and permission isolation, reader/import/native/semantic consumer migration,
retention lifecycle and operational qualification. Native Fabric tables do not
automatically resolve JSON snapshots or a new SQL active pointer. No live
consumer convergence or Phase 13/03.7/03.8 acceptance is claimed.

Source follow-ups now provide [closed SQL control procedures/clients](fabric-sql-publication-control.md)
and a separately sealed [trusted SQL/Blob server composition](fabric-sql-blob-broker.md).
They remain source-only and unqualified. The composition uses complete product
batches plus a separate pinned physical catalog namespace; a pristine SQL
control row has `session=None` until first acquisition. These additions do not
enable the default production factory or the legacy API/worker lifecycle.

## Actual row schema compatibility

Staging validates the complete product set against the registered Arrow schemas
before calling `begin` or writing any attempt object. Pinned readers repeat row
validation even when content, descriptor and catalog hashes are coherent.
Unknown columns, incompatible values, boolean-as-numeric values and lossy Arrow
coercions fail closed. Existing sparse rows and explicit `None` remain supported;
genuine integer values are compatible with floating-point fields without
rewriting the canonical JSON. This is compatibility validation, not a new
required-column or business-quality policy.
