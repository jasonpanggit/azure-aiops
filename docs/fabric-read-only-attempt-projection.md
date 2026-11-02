# Read-only immutable-attempt projection

`ReadOnlyAttemptProjector` is a distinct, explicitly composed logical projector.
It receives only exact staged-generation reads, current authorizer, a pinned
six-field target and definition-fingerprint callback, independently expected
`ImmutableLogicalProjectionPolicy` values, and an existing high-level attempt
protocol. It can be supplied to `ImmutableAttemptWorker` with the actual client
and a separately owned lifecycle journal. It does not construct a production
composition or select dependencies from candidate/dispatch data.

The staged-input port has only `read_generation` and
`read_stage_authorization`. No `service`, `local_root`, Delta writer, native
publisher, pointer or reader is required. Existing immutable staged hash,
candidate, target, current authority, stage-authorization, admission, independent
restore and exact historical recovery checks are shared with the existing
materializer. Product construction uses the same pure projection function.

The distinct logical policy binds the full generation/source/authority/target
context and every required canonical/typed logical table, including empty
tables. Each independently expected table records canonical schema digest,
row count and content digest. Runtime actual outputs are compared to this
independently supplied policy; runtime projection must never become its own
expected policy. Closed entity/relationship vocabulary checks are shared with
the fixed-table policy. Missing/extra tables or changed context/schema/count/
content are refused before broker stage. Existing client and broker row/schema
and complete-inventory verification remain authoritative.

No logical policy contains physical table or catalog destinations. Only the
broker-issued and verified immutable inventory owns physical identities.
Projection never writes a shared table, catalog or legacy pointer and cannot
confer read permission. Historical recovery is not current active/read authority.
The existing worker still provides target CAS, <=300-second/no-renewal budget,
durable intent, pre-send cancellation checks, allocation/stage ambiguity HOLD,
and exact-original-pin read-only outcome recovery.

`GenerationOutputPolicy`, fixed-table constructor/local lock and remote-root
refusal remain unchanged in meaning. The local composition still rejects
remote dependencies; it is not repurposed as a remote factory. This projector
is offline-tested source capability, not qualified access to remote inputs,
coordinator journal, broker endpoint/identity, SQL/Blob privileges or retention.
No CLI, legacy worker, pointer, reader, graph, fallback, production activation or
commissioning acceptance is introduced.
