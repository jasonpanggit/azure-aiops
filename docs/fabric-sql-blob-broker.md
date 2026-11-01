# Trusted SQL/Blob composition — separately sealed source

This follow-up composes the accepted SQL control client and independently
verified `ImmutableBlobArtifactStore` with the actual immutable-attempt
materializer/reader/restoration core. It does not modify the frozen SQL or Blob
patch artifacts, provision anything, start a service, expose an HTTP endpoint,
or enable API/worker publication. The default `AzureSqlBlobAttemptBoundary`
factory still refuses; infrastructure qualification booleans cannot enable it.

## Exact provider flow

The Blob uploader binds the **whole** artifact manifest on its first call.
Consequently, `AttemptBoundary.create_products` submits the complete product
set at once; its default implementation preserves existing sequential test
boundaries. The core validates exact returned membership and real descriptors,
not placeholder ETags. The real broker refuses single-product upload calls.

`SqlBlobPublicationBroker` owns exact SQL/Blob clients, reviewed six-field target,
retention horizon, target ID and a fixed allowed-owner set. Request boundaries
authenticate through the existing Entra JWT signature/issuer/audience/expiry
validator with explicit `subject_claim="oid"`. Existing API authentication keeps
its default subject selection. A subject string/role in a body or gateway header
is not authentication. Each operation rechecks authentication and the matching
existing `maintain_ontology` grant scope for the configured subscription; grants
requiring unavailable additional scope attributes fail closed.

Acquisition maps the verified caller oid to a DB-issued session/epoch. SQL
authority remains independent: API authentication never creates a grant.
`allocate_attempt` gets a server-issued UUID from the Blob store, never a worker
path. `begin` binds the exact candidate and target through the SQL procedure.

Product upload sends one complete set to that private namespace. The returned
`SealedBlobInventory` comes from actual create-only SDK uploads, conditional
readback and read-only ARM policy verification, not a worker-supplied dataclass
or immutability boolean. Product descriptors bind exact names, hashes, sizes,
ETags and explicit absence of version IDs.

The core validates actual row compatibility for the entire set before SQL
`begin` or any upload. The trusted composite seal independently repeats that
validation against physical product bytes, and pinned core readers validate
again even for coherent hashes. Unknown columns and lossy/coercive Arrow
conversions are rejected; sparse rows and genuine integer-to-float
compatibility are preserved without changing canonical JSON.

Only after those real descriptors exist can the broker build/verify the final
canonical catalog. It uploads `catalog.json` into a **second** server-issued
namespace: adding it to the already-bound product manifest would be invalid.
The broker verifies the complete catalog/product binding and physical catalog
readback before calling the separately authenticated SQL verifier client.
Products cannot overwrite another namespace; catalogs cannot become partial
active state. A rejected SQL transition leaves immutable orphans.

SQL evidence persists both full `product_inventory` and `catalog_inventory`
readbacks, including catalog physical identity, creation/verification times,
policy ID/ETag/retention interval and all object digests. The SQL inventory
remains the exact product descriptor list required by its existing contract.
The effective SQL horizon is the minimum observed protection end of **all**
product and catalog objects. Fixed `Locked`/versioning/append summary values
are emitted only after the actual provider verifier has checked them; no
request accepts them as qualification input. Lost seal responses reuse the
original immutable evidence, rather than rewriting the seal with newer
observation timestamps.

The composition uses `SqlBrokerVerifier.seal_owned_attempt`, not the unfenced
base seal entrypoint. Its optional SQL procedure locks the target and attempt,
checks their original owner/session/epoch and the DB-time session deadline,
and retains those locks through the existing seal transaction. Acquisition
uses the same target lock, so takeover cannot interleave with that seal.
Unexpected entry transactions are refused with a controlled `RAISERROR`
(which does not honor `XACT_ABORT`), without committing or rolling back
caller-owned work. The base SQL schema/client and their qualified suites are
unchanged; this new procedure still requires native engine qualification.

An ownership precheck cannot fence an already in-flight Blob create across
SQL and Blob. Such writes remain confined to their write-once private namespace
and may become unreachable orphans. The SQL fence prevents them from becoming
a stale seal; the independent commit fence still prevents stale admission.
No distributed transaction or zero-orphan guarantee is claimed.

`Attempt.EvidenceDigest` hashes storage-verifier evidence; the independent
`AuthorityGrant.EvidenceDigest` identifies separately validated signed-review
evidence. They have different meanings. The composition does not assume or
require equality and never replaces an authority grant with storage evidence.

This composition requires the separately sealed SQL diagnostic correction:
supported `AzureError` credential failures are sanitized alongside ODBC errors
with explicit exception families and suppressed diagnostic chaining. Unexpected
programming errors still propagate; there is no broad catch or success fallback.

## Pinned reads, retries and restart

Reads resolve the exact SQL record and its pinned physical Blob catalog, compare
the catalog's actual bytes/digest with SQL, and reject catalog/descriptor/
inventory substitution. They reconstruct the exact `SealedBlobObject` values
from persisted verifier evidence and reverify the actual provider on reads.
There is no latest-receipt, latest-version or fixed-table fallback.

The request boundary caches only verified immutable catalog/descriptor metadata,
not mutable row results. A small closed DB-time readability check runs before
each cached product read, followed by actual Blob policy/ETag/body verification.
This avoids retransferring a full multi-hundred-product inventory for every
individual product without dropping the minimum sealed retention guard.

The separate optional `sql_control/broker.sql` adds the owned-seal wrapper,
two parameterized metadata reads and procedure EXECUTE grants.
`ReadReferenceMetadata` binds immutable
generation identity for control and historical outcomes **without** artifact
authorization. `ReadReadableReferenceMetadata` also requires the sealed DB-time
horizon. Neither returns products or mutates state. Install it deliberately
after the frozen SQL schema/permissions with
`bootstrap_broker_metadata(admin_connection)` in explicit transaction mode;
it never runs on import or startup.

Exact successful outcome recovery authenticates the original caller, uses
SQL's read-only original-request lookup, and checks generation against immutable
SQL metadata. It performs no Blob read or fresh grant check, does not update
the current pointer, and survives later expiry/revocation/takeover. New commits
still use the guarded SQL transition. Restoration requires separate SQL and
existing materializer restoration authority and never reuploads products.

Unfinished uploads are different: Blob attempt handles and broker preparation
state are **process-owned**. A restarted broker cannot resume or adopt an old
unfinished handle, infer its seal, or invent an allocation record. It rejects
and requires a newly allocated attempt and independently valid authority.
Successful seals/readers and exact committed outcomes can reconstruct from
persisted SQL evidence without pretending an in-memory upload handle survived.
Original request identity/pins must be saved for ambiguous outcome recovery.

## Executed evidence versus missing qualification

`tests/test_sql_blob_broker.py` executes the real composition, real JWT crypto
validation and actual existing materializer/reader/restoration surfaces. It
injects offline Blob SDK/ARM transports and a DB-API procedure-outcome model.
Coverage includes complete batch/separate catalog namespaces, paused A/B,
caller/session spoofing, retained pinned reads, unlocked-policy refusal,
lost seal/commit responses, independent restoration, restart distinction,
retention/revocation/takeover historical recovery and persisted substitution.
The procedure model is **not** SQL engine or effective permission evidence.

`test_sql_blob_broker_engine.py` adds the explicit local-engine metadata check.
`test_sql_control_engine_adversarial.py` adopts the independent seven-case
role/concurrent-commit/receipt-failure rollback harness. Together with the
separate two-case `test_sql_control_engine_ownership_chain.py` amendment and
original SQL engine entrypoint, they remain explicitly skipped when no local
engine is configured. The amendment executes `ReadControl` as reader/broker
while direct table reads are denied, rather than relying on permission metadata.
No Docker daemon, image, cloud DB, role assignment or
policy locking is started or performed by these tests.

Still unqualified/unimplemented operational surfaces: executed T-SQL compile/
transaction/permission semantics, actual isolated SQL resources and principal
memberships, hosted broker HTTP/TLS/network configuration and worker client
transport, authoritative signed-review migration into SQL grants/revocations,
effective no-worker SQL/Blob/SAS/OneLake credentials, locked provider resources,
retention lifecycle, complete governed five-consumer migration and live
restoration/convergence. This server library and synthetic transports do not
make those predicates true. No deployment, production readiness, stronger
deadline semantics or Phase 13/03.7/03.8 acceptance is claimed.

In particular, `CandidateGenerationMaterializer` still constructs
`ImmutableAttemptProtocol(attempt_boundary)`. This server-only composition does
not inject a credential-free remote worker client into that constructor.
The next consumer seam is high-level stage/control/commit/recover/read protocol
injection and a client for the separately reviewed closed transport, not
per-product privileged RPC or SQL/Blob credentials in a worker. That seam is
not implemented by this delta.
