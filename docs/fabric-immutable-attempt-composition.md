# Explicit local immutable-attempt composition

`compose_local_immutable_attempt_worker` in
`ontology_discovery.immutable_attempt_composition` is an explicit application
entrypoint, not a CLI option, automatic factory, or production activation.
Entering its context constructs the actual broker client, local-qualified
materializer, separate lifecycle journal, and isolated worker. The application
can call `publish(candidate)` or the worker's separate trusted `restore(reference)`
command. Context construction itself acquires no token and sends no request.

All dependencies are application-owned, never dispatch or candidate overrides:
canonical HTTPS origin, exact audience, six-field target, dispatch ID, reviewed
worker object ID, credential, existing staged storage, authorizer, service,
output policies, and local document roots. The credential owner object ID must
match the worker object ID. This is a declared application binding, not token
validation or authority proof; the broker independently authenticates the
signed application/object-ID pair. Client IDs must not substitute for object IDs.
Existing client, materializer, and worker validation remains authoritative.

The lifecycle document root must be a `Path`, disjoint from both the resolved
product local root and materializer document root (including ancestor/descendant
and symlink aliases). Remote document roots and a service with `local_root=None`
are refused before transport. No local root is manufactured or assigned to a
remote service. The existing remote mutation lock refusal remains in force;
this entrypoint cannot commission a remote projection.

The context borrows credentials, staged storage, service, and materializer
documents; it does not close them. After constructing the broker client it owns
that client and the supplied HTTP transport, closing both on normal context
exit, application exceptions, or subsequent construction failure. Refusal before
client construction leaves the supplied transport owned by its caller.

Offline tests exercise actual client/closed transport/materializer publication,
persisted restart, target and worker-owner mismatch, malformed identity, root
overlap, remote-root refusal, and cleanup. This is not deployment acceptance,
current read authority, or consumer activation. Fixed-table defaults, CLI,
legacy worker, pointers, readers, graph, production gates and cloud resources
are unchanged. Real endpoint/audience/identity/grants remain commissioning inputs.
