# Combined snapshot provenance and replay

The inventory publisher and activation workflow use
`onboarding.activation.publish_combined_snapshot` to combine discovery snapshots.
New combined manifests retain `sourceConnectionIds` and `sourceRunIds` for
compatibility and add `sourceProvenance` (`combined-source-provenance/v1`).

Each source entry binds a connection ID to its exact discovery run ID, source
manifest integrity hash, collection start/completion times, declared subscription
list and query version. Missing legacy collection-time/subscription/query-version metadata is
`null`, not inferred from the current registry. Entries are ordered by connection
ID; **do not zip the independently sorted compatibility lists** to infer pairs.
Credentials, storage URLs and provider query text are not copied into provenance.

## Capture fidelity

The representation is `normalized_snapshot`. These inputs contain normalized
entities, relationships, changes and source-partition observations. They are
not certified pristine provider responses. Collection timestamps are not provider
observation times. Existing row-level source/partition clocks and unavailable or
stale states remain intact; a completed snapshot does not establish acquisition
completeness or current consumer readiness.

Provenance describes the selected discovery inputs. It does not claim a complete
per-column dependency graph, nor an independent upstream-generation binding for
caller-supplied `pinned_datasets`. All materialized combined artifacts, including
those supplied datasets, remain covered by combined-generation integrity checks.

## Integrity and pinned input reads

`DatasetStore.read_verified_generation(run_id)` reads a retained generation by
exact ID, checks completed status, identity, every declared artifact's row count,
semantic hash and full JSON integrity hash, and the overall manifest integrity
hash. It returns the rows that were actually verified. Aggregation consumes those
rows, not a later read of `current`; a pointer change cannot mix generations.
Corrupt or absent inputs fail before publishing a combined generation. A reused
run ID is resolved through the exact selected writer-generated directory, including
sanitized names and collision suffixes, and its unchanged manifest identity is
checked separately. Equal run IDs in distinct connection roots remain distinct
source bindings. No fallback to current or an older unsuffixed directory occurs.
Source manifests without the existing integrity contract fail explicitly;
they must be regenerated through their normal discovery flow, not silently trusted.

Integrity hashes detect inconsistency. They are **not signatures, access grants,
remote writer fencing, or WORM guarantees**. This implementation preserves the
existing trusted-storage assumptions.

## Replay and retention

The existing exact activation replay path calls
`verify_combined_activation_generation` before constructing a publication runtime.
It now additionally validates explicit provenance when present: contract version,
connection/run membership and uniqueness, digest shapes, capture representation,
scope types and timezone-aware ordered collection timestamps when recorded.
Missing legacy collection timestamps remain null; malformed recorded timestamps
still reject.
Existing integrity-valid manifests without `sourceProvenance` remain replayable,
but their connection/run pairings remain unrecorded; no provenance is invented.
Unchanged-generation reuse compares the full mapping, not just the two ID sets.

Replay uses the retained **combined** snapshot. It does not rerun acquisition,
recompute normalization from live providers, or require the original discovery
generation to remain present. The original source digest remains historical
evidence, not a claim that the source can still be fetched. Ordinary Fabric sync
and its checkpoint behavior are unchanged; this is not a new replay endpoint
or a replacement publication-authority mechanism.

Existing generation cleanup still retains three generations. Optional long-term
history, raw-query capture and retention expansion are **not enabled**. A pruned
combined generation is unavailable for replay and must not fall back to current.
No schedule, role, identity, schema registry, cloud resource or consumer routing
is changed by this source implementation. Live rollout and acceptance are separate.
