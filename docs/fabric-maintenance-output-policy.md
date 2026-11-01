# Maintenance output preflight (local-only, authority none)

`fabric.maintenance_output` supplies an immutable, opt-in Python interface for
the maintenance path, not a live contract loader or execution permission.
There is no CLI/environment switch, publisher-runtime composition, native
adapter, cloud access, or populated live policy in this increment.

`CandidateGenerationMaterializer(isolated_output=True, output_policies=(...))`
requires server-owned policies before construction succeeds. Supplying policies
also enables the requirement even if the boolean is omitted. Each policy binds
one exact operation (`admission` or `restoration`), staged-manifest digest,
generation/source/content, validation digest, authorization/attestation digests,
and the existing six-field maintenance target. Restoration needs its own
retained-generation policy; an admission policy is not reusable as restoration
authority. Existing staging validation, admission/restore authorization,
mutation lock, per-write lease/authority guards, version-pinned readback and
receipt checks remain in place.

The service checks candidate **types and relationship triples, including
inactive rows**, against the complete source registry before product generation.
It then compares the complete generated manifest with the independently
supplied policy before the first Delta or catalog call. The inventory includes
empty tables, exact logical names, workspace/Lakehouse/schema and physical
destinations, serialized Arrow schema fingerprints, canonical row-multiset
digests (duplicates retained), row counts, fixed OVERWRITE mode, and the complete
catalog URI/schema/generation/content/table membership. Catalog `deltaVersion`
is `null` in the expected preflight template: actual returned Delta versions are
the only fields filled after writes. Native publication must be absent and
native targets empty. A missing/extra/final-table or catalog mismatch is not
deferred until partial publication.

Policies reject duplicate/ancestor-alias destinations and overlap with any
explicit protected root. Local paths resolve symlinks and conservatively
case-fold; ABFSS protected-root identifiers reject encoded separators,
dot/empty segments, query/fragment and backslashes. This is a declared protected
registry, not independently authenticated production inventory.

The supported sink is an exact, local `OneLakeWriter`. Remote/custom sinks fail
closed rather than inheriting unverified cloud behavior. The effective writer
target (including local root, IDs, table schema and storage-options hash) is
fingerprinted, not its YAML path or environment shorthand. Local destinations,
writer configuration, schemas, candidate/products and catalog are snapshotted;
each consequential sink retains the authority guard and rejects observed
target/native/sink replacement. Caller input and sink row mutation cannot
redirect later products. Diagnostics contain reason identifiers, not payload,
environment or storage-option values.

All table and catalog canonical destination identities are frozen at preflight.
After each authority callback and before **every** sink, all destination path
components (including Tables, Files, catalog parents and final paths) are checked
for symlinks. Descendant symlinks are conservatively rejected even if they point
inside the target; a first-callback redirect of either table or catalog parents
therefore yields zero product sinks. Midrun redirects stop remaining sinks.
This closes callback/scheduling-boundary substitution in the cooperating local
writer model; it is **not** an atomic no-follow/openat boundary. An adversarial
process changing filesystem components concurrently between check and sink,
mount replacement, or arbitrary sink implementation mutation is unsupported.
Local flock coordinates participating materializers, not unrelated filesystem
actors. No broader atomic filesystem isolation is claimed.

## Deliberate limits

`describe_outputs` is a pure description helper for offline tooling/tests and
comparison. Computing it from the candidate during publication **must never
create the expected policy**. Synthetic empty-input tests establish coverage,
not a universal 708-table allowlist or independent consumer qualification.

This coherent local guard interface does not implement the complete central
`maintenance-output-manifest-design/v1` qualification document. A future
reviewed composition must independently bind source SHA, isolated-contract
digest, complete resolved runtime-config digest, protected-production contract
and disjointness evidence, publisher client identity, and immutable candidate
admission/restoration policies. The existing materializer exposes staged
manifest/validation and six-field target context, but no authenticated resolver
for those additional provenance fields. This increment neither invents them
nor treats its effective local writer fingerprint as the full resolved runtime
configuration. Cloud sink snapshot/atomicity and authenticated policy loading
remain unsupported; no production runtime is enabled by this interface.

Preflight rejection means **zero Delta/catalog/native calls for that
invocation**. Lease, journal and other control writes may already exist.
Authority loss or target mutation discovered after an earlier successful write
stops subsequent writes; it does not retroactively imply zero previous writes.
Legacy service/materializer callers without policies and broad `sync` retain
their prior behavior and existing maintenance refusals.
