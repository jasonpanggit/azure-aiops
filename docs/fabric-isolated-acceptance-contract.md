# Inert isolated acceptance contract

`ontology_discovery.isolated_acceptance_contract` provides an **opt-in local
schema and loader only**. It is not imported by the deployed collector, live
validator, publisher, coordinator or Job-start paths. Their existing production
image equality, fixed-name, identity, root and authority checks are unchanged.
Phase 13 acceptance and Phase 03.7/03.8 prerequisites remain unchanged.

## Document states

The version is `isolated-acceptance/v1`, with purpose
`offline-contract-validation` and authority `none` in every state.

| State | Required content | Meaning |
|---|---|---|
| `draft` | Header, source SHA, self-digest and nonempty unresolved-field list | An explicitly incomplete design; no reviewed bindings or qualification inferred |
| `reviewed` | All binding, freeze and referenced-artifact fields | Complete **declared** reviewed configuration, not authenticated review or permission |
| `qualified` | All reviewed fields plus exact consumer/capability receipt registries | Complete **declared** qualification claims, not verified live acceptance |

These are separate discriminated types. A draft can parse without live receipts,
but cannot pass `require_qualified_contract`. A reviewed document cannot silently
omit live binding fields to accommodate an incomplete candidate.
`require_qualified_contract` still returns inert data; it is **not an execution
or authorization entry point**. This module has no signing trust root, approval
verification, cloud adapter or authority to promote any deployed baseline.

`contract_json_schema()` returns the structural JSON Schema. Cross-field,
canonical-path and referenced-byte invariants are additionally enforced by the
loader, not expressed solely by the generated schema.

## Binding inventory

Complete documents require explicit immutable image pins for API, web,
coordinator, RBAC validator, fixture prepare/cleanup, evidence reader, validation
publisher and protected production publisher. Distinct role pins are allowed;
each Job must match its own pin. No expected pin is inferred from observations.

The closed six-role Job registry binds full subscription/resource-group Job IDs,
managed-identity resource IDs, client IDs, images and saved-template byte
references. Runtime Job-start authority is forbidden. Jobs cannot alias each
other or substitute for the protected production publisher. The validation
publisher retains the explicitly pinned publisher identity. Protected API and
publisher images and preimage references are mandatory. Current publisher freeze
evidence does **not** explain historical divergence; that disposition remains
`unresolved`.

The contract requires all seven capability roots (connection, state, command,
dispatch, publication, fixture and drill), protected production roots, resolved
Lakehouse Tables/schema and native-item targets, five distinct logical consumer
surface bindings, and the exact six-field maintenance target:
`tenant_id`, `subscription_id`, `connection_id`, `workspace_id`, `item_id`,
`definition_fingerprint`. Maintenance authorizer/observer and fixed
arm/inspect/resume/cleanup template references are mandatory.

All roots use explicit GUID-based ABFSS OneLake `Files` paths. Authority/GUID and
path comparisons are conservative and case-insensitive, and compare path
segments rather than string prefixes. Equal or ancestor/descendant capability
aliases fail; sibling names do not overlap. Escapes, dot segments, empty
segments, queries, fragments, control characters and unsupported spellings fail
closed rather than being silently normalized. Tables and native items are
separately typed: a new `Files` prefix cannot isolate production Tables.
An explicit different canary workspace/Lakehouse can isolate Tables at the
configuration level; it does not prove effective write/CAS/delete capability.

The resolved-configuration artifact must match the declared effective roots,
materialization, consumers and maintenance target. Consumer materialization
fingerprints bind those exact targets. The configuration source is immaterial:
`FabricRuntimeConfig.load` can consume a complete
`AIOPS_FABRIC_CONFIG_JSON` override before YAML. Freeze the **resolved targets**,
not the environment variable name or YAML path.

## Local byte verification and limits

`load_contract(path, artifacts=...)` reads one local JSON file and receives an
explicit mapping from artifact keys to bytes. It does not resolve artifact
paths, fetch URLs or discover missing dependencies from the environment.
Every artifact reference is SHA-256 checked against those exact bytes.
Contract digests use sorted-key, compact UTF-8 JSON with nonfinite values
forbidden, excluding **only** the top-level `contract_digest` field. Duplicate
JSON keys, unsupported versions, unknown model fields and missing fields fail.
Reviewed state, plan, review, template, protected preimage and authorizer
references are byte-bound freeze inputs, not semantic validation of Terraform
plans, Job commands or authorization policy. Existing validators are not bypassed.
No reference can be reclassified as accepted merely because its observed hash
is stable.

Qualified documents require separate consumer and capability receipt artifacts.
Consumer receipts bind the source SHA and exact logical consumer binding;
capability receipts bind the Job/resolved/protected registry. Each receipt
contains a closed `direct_observation` record with a further digest-bound
observation artifact. Missing, mismatched, reused receipt artifacts or
manifest-complete/validation-passed metadata echoes do not satisfy that schema.
Hashes prove byte integrity only; neither the collector identity nor the
truth/quality of opaque observation bytes is authenticated by this loader.

Observer kind is explicit: `in_process_surface`, `external_client`, or
`effective_capability`. The existing five `ProductConsumerPorts` are in-process
pinned Delta/service/catalog surfaces, not independently authenticated HTTP
API/agent/export/semantic clients. Loading an in-process receipt does not turn it
into external-client evidence.

The publisher's missing-maintenance-observer refusal is conditional on a
production reader being selected. It is not evidence that the retained
production publisher currently fails startup. Injected maintenance in production
runtime mode remains refused. This schema does not install observer bindings
or change runtime mode to evade that gate.

## Remaining qualification boundary

Unified Deployment must instantiate and review exact bindings, reconcile saved
plans/state, freeze protected preimages and obtain effective-access, lifecycle,
drill, materialization and consumer/rollback evidence through existing governed
processes. Synthetic tests only exercise parsing and structural rejection.
There is no populated live contract or accepted baseline in this increment.

Focused offline checks:

```sh
.venv/bin/python -m pytest tests/test_isolated_acceptance_contract.py \
  tests/test_ontology_deployment_plan.py tests/test_ontology_discovery_live_evidence.py
.venv/bin/ruff check src/ontology_discovery/isolated_acceptance_contract.py \
  tests/test_isolated_acceptance_contract.py
```
