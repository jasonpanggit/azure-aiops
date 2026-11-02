# Isolated immutable-attempt worker lifecycle

`ImmutableAttemptWorker` is an explicit, source-only coordinator for one
trusted dispatch. Application composition supplies the fixed dispatch ID,
exact target, already configured `PublicationBrokerClient`, immutable-mode
`CandidateGenerationMaterializer`, and a separate lifecycle-journal port.
Candidate or request data cannot select or replace these dependencies. The
worker is not wired to the CLI, legacy worker, reader, active pointer, or
consumer graph.

## Lifecycle contract

For publication, the worker creates a journal record binding the dispatch,
target, operation, and canonical candidate digest before broker activity. It
reads the broker control revision, records it, and acquires against that exact
revision with a lease from 1 through 300 seconds. It never renews. It records
allocation and staging intent before each call. If allocation or staging has
an ambiguous outcome, it persists `held` and never retries or reallocates.
Mismatched dispatch reuse is rejected before contacting the broker.

The client checks cancellation and the monotonic lease deadline immediately
before the HTTP send, after token acquisition, so credential latency cannot
carry an expired or cancelled operation across the mutation boundary.
Cancellation before a send persists `held` without making that send. Commit or
restore request pins are journaled before the boundary call. If that call has
an ambiguous outcome, recovery uses only those exact original pins and the
client's read-only historical-outcome operation.
Missing pins, no recorded outcome, or failed recovery cannot trigger a new
commit. A recovered outcome is recorded as `historical_recovery`; it does not
assert that the reference remains active or that product reads are authorized.

Restore is a separate operation bound to one exact retained reference, a new
dispatch identity, and fresh materializer restore authority. The dispatch
journal is opened and checked before any catalog lookup; a restart with saved
restore pins can recover the exact historical outcome without re-reading the
catalog. A new restore uses a new request ID and the same bounded acquisition,
journal, and recovery rules. It never changes retained artifacts.

`OneLakeAttemptLifecycleJournal` keeps durable dispatch receipts under
`ontology/immutable-attempt-lifecycle/dispatches/` and serializes ownership
through a target-keyed create-only/ETag-CAS record under
`ontology/immutable-attempt-lifecycle/targets/`. A competing dispatch cannot
replace a target owner whose receipt is in progress or held. Acknowledged or
historically recovered dispatches may be superseded by a later trusted
dispatch; their per-dispatch receipts remain unchanged. A held target remains
blocked rather than being silently released. Both journals are separate from
fixed-table products and the materializer's legacy recovery journal. The
materializer retains its local-root and target checks; no remote-root lock
relaxation or production factory is added.

## Verification boundary

`tests/test_immutable_attempt_worker.py` drives the actual client through the
existing closed in-process broker transport and the actual materializer. It
covers successful isolated admission, dispatch/candidate mismatch, durable
HOLD after lost allocate/stage responses, restart without reallocation,
cancellation/deadline expiry after token acquisition but before stage send,
cancellation before commit send, exact-pin read-only recovery after a lost
commit response, and separate restore with new request pins. It also checks
local journal CAS, per-target conflict behavior across worker restart, receipt
preservation when a terminal target owner is superseded, read-only recovery
credential and transport failures persisting as HOLD, and the absence of
fixed-table product writes.

This is offline source evidence only. No live broker, cloud resource,
production identity, credential grant, native Fabric reader, CLI/legacy
worker, pointer migration, graph projection, or consumer activation is
configured or qualified. Unified owns commissioning and release coordination.
