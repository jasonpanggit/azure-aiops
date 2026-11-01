# Worker publication broker HTTP client

`ontology_discovery.publication_broker_client.PublicationBrokerClient` is an
inert, high-level worker counterpart to the separately sealed authenticated
broker transport. It implements the structural `ImmutableAttemptProtocol` API,
not `AttemptBoundary`. Nothing instantiates it by default. This change does not
add routes, a serving process, consumer injection or a production factory.

## Constructor-owned trust

An explicit composition supplies one exact HTTPS broker origin, its exact Entra
application audience (UUID or `api://UUID`), the complete six-field expected
target, the reviewed worker object UUID and an injected scoped `TokenCredential`.
There are no per-call URLs, headers, bearer strings or target overrides. The
only requested token scope is `<audience>/.default`. The credential must be a
worker identity with only the reviewed broker application permission, not SQL,
Blob, verifier, grant or artifact-account permissions.

An optional `httpx.BaseTransport` is an explicit trusted test/hosting dependency.
The owned HTTP client does not follow redirects or use environment proxies.
The default transport has zero retries and ordinary HTTPS certificate checking.
Closing this client also closes its injected transport.

The client does not authenticate callers or confer publication authority.
The independent server transport verifies signature, issuer, audience, tenant,
app-only mode and the reviewed application/object pair; composition re-verifies
the original bearer and enforces SQL-issued sessions. Request bodies contain
only opaque session ID and epoch, never a caller-asserted owner.

## High-level API and closed wire operations

| Method | HTTP operation |
|---|---|
| `control()` | `read-control` |
| `active()` | one control snapshot, then its exact `read-catalog` if active |
| `acquire(*, expected_revision, lease_seconds=300)` | `acquire` |
| `allocate_attempt(session)` | `allocate` |
| `stage(session, *, attempt_id, candidate, products)` | one complete `stage`, then exact `read-catalog` verification |
| `commit(session, reference, *, expected_revision, operation, request_id, authorization_digest)` | `commit` |
| `recover_commit(...)` | `recover`, with the identical original pins |
| `read_catalog(reference)` | `read-catalog`, returning a dictionary |
| `read_table(reference, table)` | exact `read-catalog`, then `read-table` |

All eight endpoints are fixed POST paths under `/publication/v1/`. Stage
snapshots all products and validates actual rows using the corrected core's
shared `_validate_product_rows`, before obtaining a token or sending HTTP.
Unknown columns, boolean-as-number, lossy conversions and nonfinite JSON
refuse; sparse rows and compatible numeric integer-to-float values remain valid.
No per-product write, raw SQL, Blob object URL, verifier or grant API exists.

## Response validation

Responses must be bounded, uncompressed JSON with exactly one `result`.
Duplicate fields, named nonfinite constants, exponent overflow, malformed
identity fields and unknown envelope fields refuse. Requests are limited to
8 MiB and responses to 16 MiB. Fixed errors omit response bodies, tokens,
credential diagnostics and HTTP exception messages.

Control responses require exact revision/session/reference shapes. Acquisition
and transition outcomes must belong to the constructor-pinned worker. A commit
or recovered result must match the original session, exact reference and
predecessor revision plus one, not a newer control snapshot.
Only pristine read-control may return `session=None`, with `revision="0"` and
`active=None`. The client preserves that state without inventing an owner or
automatically acquiring. Present acquisition/transition outcomes remain
non-null and owner-bound.

The trusted broker performs full sealed-catalog/product readback validation.
The worker independently verifies returned catalog digest, attempt/generation,
constructor target, schema fingerprints and closed artifact descriptors.
`read_catalog` deliberately does not recursively fetch all tables: it exposes
metadata, not unvalidated row values. `read_table` additionally verifies the
requested product's canonical content digest, exact length, row count and
actual registered row schema before returning rows. This avoids quadratic
high-level HTTP read amplification while preserving exact immutable pins.
Catalog-provided artifact URLs are never followed.

## Ambiguous outcomes and explicit recovery

There are no automatic mutation retries, automatic recoveries or latest-state
fallbacks. A timeout after a mutation is ambiguous even if the server committed.
Persist the original session, full attempt reference, predecessor revision,
operation (`admit` or `restore`), request UUID and authorization digest before
committing. An explicit `recover_commit` submits exactly those pins once and
does not first fetch control, catalog or products. Server-side authenticated
historical recovery may therefore succeed after lease expiry, owner takeover
or later retention/authority changes without repeating publication side effects.

Only an authenticated absent recovery outcome returns `None`. Other errors or
malformed/null results raise; a missing active pointer is represented by the
protocol's `(None, None)` active tuple. Lost acquisition/allocation/stage
responses are not secretly repeated or converted into success.

## Source dependencies and qualification boundary

This client requires the separately sealed actual-row schema correction
`656d328333955c1ed67f1062e2fc42d21a64993dab6ea9a6b3866db9962f62be`
and corrected authenticated transport
`86ed78ec423df05d26d5423e5e55db7b0e8da4a42632eedb2f9135b5b52eb638`,
with their declared prerequisites. Do not silently use older fingerprint-only
core validation or the superseded transport.
The nullable-control shape is coupled to split composition
`ac24df8cc1fb94d2674344fd82ac06cab753e9e611ae4d22570081fd75c3833a`
and the separate additive `fabric-publication-broker-pristine-control.patch`.
Do not stack the superseded combined composition with its split corrections.

Offline tests exercise actual signed Entra JWT verification through the accepted
transport using injected HTTP, conditional protocol fixtures and the real
SQL/Blob composition backed by injected DB-API, SDK and ARM transports. They do not
qualify SQL engine transactions/permissions, live Locked Blob policy, hosted
HTTP/TLS/network configuration or consumer migration. Consumer injection,
routes/startup, credentials/grants and execution enablement remain separate,
explicitly unimplemented lanes. No cloud calls or deployment are authorized.
