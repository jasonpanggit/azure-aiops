# Inert authenticated publication broker transport

`ontology_discovery.publication_broker_transport` is a closed HTTP request codec,
**not a deployed broker**. It installs no ASGI route, server, client, CLI,
credential factory or environment switch. No live permissions, SQL engine,
identity registration, private connectivity or consumer migration are qualified.

## Constructor-owned identity and target

`PublicationBrokerTransport` requires a canonical tenant UUID, one exact audience,
one explicit worker application role, an exact six-field target, reviewed
`ReviewedWorker(application_id, object_id)` **pairs**, and a trusted
`BrokerRequestFactory`. Separate application/object lists are not cross-multiplied.
Configuration is copied and frozen. There are no wildcard workers, delegated-user
fallback, shared-key assertion mode or default enablement.

The transport reuses the actual repository `api.auth.EntraJwtAuthenticator`, its
Entra v2 issuer/JWKS configuration and RS256 signature/issuer/audience/time
verification. That class returns an API `Principal`, not signed claims. The
transport therefore additionally verifies the **same immutable bearer** with its
existing JWKS client to obtain claims; it never trusts an unsigned JWT decode.
An internal reader grant only satisfies the existing verifier's principal
construction contract. It is not returned, not passed to composition and grants
no broker authority.

Transport policy requires exact signed `tid`, `oid`, `azp`, `ver="2.0"`,
`idtyp="app"`, the exact configured string audience and required role. Missing
claims reject. An audience alias/list, other tenant, unreviewed app/object pair,
`scp` (even empty), username/UPN mode, conflicting `appid`, malformed roles,
expired/future token, wrong issuer/signature/algorithm all reject. This deliberately
supports only explicitly configured v2 app-only tokens; app registrations must
emit the required claims/role. It does not infer a managed identity from headers
or assume every tenant currently emits `idtyp`.

HTTP headers are a bounded sequence of name/value pairs so duplicate
case-insensitive Authorization headers cannot collapse into an accepted value.
Only one unchanged bearer header is forwarded in an immutable mapping. Gateway
assertions and caller principal/owner headers are ignored, never used to authorize.

## Composition interface and server-owned sessions

`BrokerRequestFactory.for_request(original_bearer_headers)` returns an
`AttemptBoundary` bound to the independently reauthenticated worker. The actual
composition must own exactly the same reviewed target and required scope; it must
not trust a transport-supplied `Principal` or accept a payload-selected factory,
target or credential. This is a trusted constructor composition seam, not a
runtime provider/permission attestation. The separate composition lane owns
`SqlBlobPublicationBroker.for_request`, not this module.

The returned boundary also supports:

```python
acquire(*, expected_revision: str, lease_seconds: int) -> AttemptControl
allocate_attempt(session: AttemptSession) -> str
```

Acquisition maps the verified `oid` to a server-issued SQL owner/session/epoch.
Subsequent bodies carry **only** original opaque `session_id` and `epoch`.
The transport reconstructs `AttemptSession.owner` from the verified `oid`, never
from a body/header field. Composition independently authenticates the bearer and
checks the owner and session. The client cannot create authority by guessing
session pins. Process-owned attempt allocation/restart limitations remain those
of the separately accepted Blob/composition model.

## Closed HTTP contract

`handle(method, path, headers, body)` accepts only POST to these fixed paths:

| Suffix under `/publication/v1/` | Exact JSON fields |
|---|---|
| `acquire` | `expected_revision`, `lease_seconds` |
| `allocate` | `session` |
| `stage` | `session`, `attempt_id`, `candidate`, `products` |
| `commit`, `recover` | `session`, `reference`, `expected_revision`, `operation`, `request_id`, `authorization_digest` |
| `read-control` | none (empty object) |
| `read-catalog` | `reference` |
| `read-table` | `reference`, `table` |

`session` is exactly `{session_id, epoch}`. `reference` is exactly
`{attempt_id, generation_id, catalog_digest}`. Commit operation is `admit` or
`restore`. UUIDs must be canonical, revisions nonnegative bigint-shaped strings,
digests lowercase SHA256 and leases integers 1..300 seconds (not booleans).
Candidate and expected-target fields are closed, with exact constructor target
equality. Only `ontology_*` product names and complete row lists are accepted.
Actual row-schema validation remains the core/composition's responsibility;
this transport's shape checks do not qualify the separately identified core
schema correction.

Bodies are completed byte strings, at most 8 MiB, with duplicate JSON keys,
nonfinite constants and malformed/deep JSON rejected before composition is called.
Numeric exponent overflow (both signs, at any JSON depth) is also rejected by
an explicit finite `parse_float` hook; ordinary finite exponents remain supported.
There is no arbitrary HTTP path/query, SQL, seal/verifier, grant/revoke,
credential, policy, delete or provision operation. The transport uses the real
`ImmutableAttemptProtocol` for staging, pinned reads and commit/recovery; it does
not implement a second pointer or direct store writes.

Successful results are wrapped in `{"result": ...}`. Acquisition/commit results
include opaque server session pins; the returned owner must match the verified
caller. Control reads may describe the current owner without granting ownership.
Only `recover` can return null for an absent historical outcome. Exact recorded
outcomes remain historical and do not authorize expired artifact reads or
reapply a pointer; absent outcomes must still satisfy fresh commit checks.

Authentication errors return fixed 401, unknown methods/paths 404, malformed
bodies 400 and publication safety refusals fixed 409. No input/provider diagnostic
is interpolated. Other infrastructure exceptions propagate to the future serving
host, **not** to a success/null fallback; this codec alone is not a production
error middleware, rate limiter, listener, TLS endpoint or request-body streamer.
The eventual host must enforce ingress size/time/concurrency limits and sanitize
infrastructure failures without exposing tracebacks.

## Offline evidence and remaining gates

Tests use genuinely signed RSA JWTs and the actual repository JWT verifier with
an injected local JWKS key (no token/JWKS/network calls). They prove authentication
and closed-body rejections occur before factory invocation, header/body identity
spoofing cannot supply ownership, exact target/pair pins and full protocol
stage/commit/pinned-read/historical-recovery behavior against the existing
test-only enforcing boundary. These are not Entra deployment, SQL-engine or
Blob-provider tests.

Before any service rollout: separately qualify the authenticated composition,
core row schemas, SQL engine semantics, actual Entra app roles/claims/effective
access, issuer key rotation, dedicated credential isolation, trusted verifier/
authority services, WORM retention and private connectivity. No such qualification
or deployment authorization is conferred by this source increment.
