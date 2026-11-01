# Offline isolated role-image saved-plan subset

`scripts.validate_isolated_saved_plan.validate_isolated_saved_plan` explicitly
loads the strict contract and its digest-verified original validation plan bytes.
It does not modify a plan, rewrite worker images, discover current pins, or call
cloud APIs. No collector, runtime, CLI or Job execution caller is connected.
Its result is `isolated_plan_semantic_subset_verified`, `authority: none`;
declared reviewed status is not authenticated approval.

The existing complete typed image registry is sufficient; no schema extension or
arbitrary address/root override is introduced. A private shared plan-check core
now accepts a complete internal worker-role map. The original
`validate_saved_plan` signature and behavior remain: its wrapper supplies the API
digest for every worker/fixture as before. Only the new opt-in function supplies
the contract's coordinator, validation-publisher, RBAC and individual fixture
pins at the fixed existing Terraform addresses. API/web retain their own pins.

The same address allowlist, destructive-change scan, single-container checks,
API identity/authority rules, validation classification, fixture names/commands/
identity/retry/root suffix rules and marker checks run on the original plan.
The new function additionally checks exact frozen Job IDs/names, UAI association,
client IDs, full image references, required per-role capability roots and their
contract values. Duplicate resources/changes, nested unsupported resources and
planned-value/change-after disagreement fail closed. Production publisher IDs
are excluded from both planned targets and change preimages; they are not merely
allowed under another digest.

The existing `ontology_publisher` Terraform address is interpreted as the
explicitly bound validation Job in this isolated-plan subset. This does not
permit retargeting the deployed production publisher: a production publisher
preimage is rejected. A future real plan must use the governed state separation
and reviewed mapping; this tool does not generate or apply it.

This is not a broadened Terraform rollout contract. Evidence-reader Jobs and
separate production protected resources are not added to the legacy address
allowlist. Their pins remain mandatory in the full contract but are not claimed
as planned by this subset. Protected publisher preimage semantics and effective
live unchanged-target proof remain separately unqualified. Existing fixture
root suffixes still apply, so a candidate with incompatible proposed paths fails
rather than obtaining a root override.

Tests exercise distinct API/coordinator/fixture/validation-publisher pins only
through the opt-in function, unchanged legacy rejection, wrong/missing pins,
production substitution/preimages, destructive/unapproved/nested addresses,
extra containers, identity/root changes and inconsistent raw plan projections.
