# Explicit remote immutable-attempt context

`remote_immutable_attempt_context` is an explicit, inert application context.
There is no production caller, runtime factory, configuration/discovery path,
CLI wiring or default activation. Entering it performs no token, provider or
broker request. Only an explicit call on the yielded worker starts a lifecycle.
This is source composition, not commissioning acceptance.

The application supplies the pinned broker HTTPS origin/audience, worker object
ID and reviewed credential-owner declaration plus borrowed credential. It also
supplies stage/journal canonical roots, separately declared owners and borrowed
credentials; an exact six-field definition target and dispatch; current
authorizer and definition fingerprint callback; and independently planned,
complete logical policies. No deployment values or credentials are discovered,
substituted or derived from candidate payloads.

The context reuses `bind_remote_attempt_documents` for canonical disjoint roots,
distinct declared stage/journal owners and lazy SDK lifetimes. Its narrow staged
reader feeds `ReadOnlyAttemptProjector`, bound to the actual
`PublicationBrokerClient`. Separate journal documents feed
`OneLakeAttemptLifecycleJournal` and the actual `ImmutableAttemptWorker`.
Existing policy/content/current-authority, per-target CAS, exact recovery, HOLD,
independent restore, cancellation/deadline and hard lease-budget rules are
unchanged. Broker inventory alone determines physical publication destinations.
No local mutation-lock bypass or fake `local_root` is needed; local composition
and fixed-table behavior are untouched.

The context owns its document stores and their lazy SDK clients. After broker
client construction it also owns the HTTP client and injected transport,
closing them even if projector/worker construction or the context body fails.
Earlier validation/client-construction failure leaves the injected transport
borrowed. Application credentials and the authorizer remain borrowed and are
never closed. The yielded worker must not be used after context exit.

All identity provenance is reviewed caller declaration, not token-principal or
RBAC evidence. Broker worker ownership is separate from staged/journal ownership;
Python credential object identity does not prove a principal. There is no
commissioning-ready flag. Actual roots, owners, permissions and current worker
authority remain independently unselected/unproven. The reported DEV Blob
immutability state (Deleted/0 days) remains an external commissioning blocker,
not something this context repairs or qualifies. Historical recovery is neither
current active authority nor proof of read access.

Offline tests combine fake SDK storage with the existing closed HTTP broker
transport; no cloud/provider, native/engine, pointer, reader or graph integration
is involved. Production activation and commissioning remain separately blocked.
