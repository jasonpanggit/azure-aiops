# Offline semantic artifact subset

`scripts.verify_isolated_acceptance_artifacts.verify_artifact_semantics` is an
explicit, disconnected local verification function. It imports existing **pure
validation helpers**, not their CLI entry points. It does not read cloud state,
select environment defaults, discover missing bytes or create an execution path.
Its successful result is `semantic_subset_verified`, with `authority: none`;
this is not review authentication, acceptance or deployment permission.

The accepted inert contract loader remains unchanged. This additional function
first loads that contract and checks all referenced-byte digests, then requires
a closed `SemanticExpectations` object pinned to the exact contract digest.
Expected template hashes, commands, arguments, timeouts, trigger/retry/single-
replica settings and environment-name registries are explicit inputs. They are
not learned from the observed snapshot. Like the original loader, this function
does not authenticate who supplied those expectations.

## Supported raw formats and existing checks

Production/validation plan references must contain full `terraform show -json`
plan objects accepted by `validate_saved_plan`. The existing helper's complete
address, destructive-change, environment, fixture, identity and API/worker image
checks run unchanged. Failure is propagated as a sanitized `PlanValidationError`.
Distinct worker/API image plans remain **unsupported and rejected**. No plan is
rewritten, translated or rehashed to evade the legacy contract.

Each of the six Job template references must contain a restricted raw ARM Job
snapshot with top-level `id`, `name`, `identity`, and `properties`. Supported
execution fields are:

- Identity `type` and `userAssignedIdentities`, with assigned `clientId` and
  optional `principalId`. Exactly the pinned UAI is required.
- Properties `configuration` and `template`; the template contains only a single
  `containers` list, with no init containers or volumes.
- Configuration `triggerType`, `replicaTimeout`, `replicaRetryLimit`,
  `manualTriggerConfig`, and absent/empty schedule/event trigger configurations.
- Container `name`, `image`, `command`, `args`, `env`, `resources`; resources only
  `cpu`/`memory`; explicit environment `name`/`value` rows without duplicates or
  secret references.

Other fields are rejected, not silently stripped. This deliberately does not
accept unrestricted ARM GET documents with additional fields. No GET-only
normalization is implemented: a future broader raw format needs a separately
reviewed closed projection before use. Do not remove execution-relevant fields
to make a document pass.

`assert_fixed_template` checks the existing Plan 19 execution projection hash.
Because that historical projection retains identity count rather than exact UAI
keys, this new layer separately compares full ARM target ID, UAI association and
client ID. ARM ID/name/UAI matching is case-insensitive and exact, never a suffix
match. Extra identities, containers, fields or environment names fail closed.
Command, arguments, image, finite timeout, manual trigger, zero retry and
single-replica completion/parallelism must match explicit expectations. Publisher
identity class/client binding is checked without changing any runtime mode.

## Intentional limits and missing shapes

This subset checks validation-registry Job snapshots, not the opaque protected API
and publisher preimage bytes, Terraform state semantics, authorizer policy or
review signatures. Their original byte-integrity requirements still apply.
Protected preimages currently have no declared discriminated raw type:
`api_preimage` could be an app snapshot, while `publisher_preimage` could be an
ARM Job snapshot or an already projected comparison. Further semantic checks
require explicit versioned raw kinds and a separately pinned protected
identity/command/environment policy; accepting any guessed shape would be unsafe.

The existing saved-plan helper is sufficiently specified to reuse as-is, but it
cannot certify the proposed distinct-image isolated rollout. Supporting that
rollout requires a separately reviewed saved-plan address/image contract, not a
relaxation inside this function.

Errors name sanitized structural checks and never include environment values.
Raw artifacts stay in caller-supplied local memory. The original loader's
draft/reviewed/qualified separation and lack of execution authority are unchanged.

Synthetic tests cover raw artifact corruption/substitution, exact and extra UAI
association, wrong ARM target, command/image/retry/timeout changes, stale
projection hash, unmodeled execution fields, secret-value redaction, destructive
and unexpected plan addresses, legacy distinct-image rejection, and no CLI
fallback for absent bytes.
