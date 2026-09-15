# Phase 3 Follow-up: Azure SRE Agent Patch Execution

## Status and scope

This is a source-only follow-up to Phase 3 Safe Remediation Execution. It adds
an alternative, default-off Azure SRE Agent execution and verification path
behind `AIOPS_PATCH_EXECUTION=sre-agent`.

This follow-up does **not** reopen Phase 3, change the active Phase 4 plan, or
modify or satisfy any Phase 4 entry gate. In particular, it makes no claim
about the exact Defender digest-to-workload traversal, qualified 100k
benchmark, or canary/rollback evidence retained in `.planning/STATE.md`.

## Required behavior

- Keep the existing refusing default and direct ARM adapter unchanged.
- Reuse the existing approved immutable execution snapshot and durable
  pre-submit claim.
- Permit only exact, non-empty VM/Arc `install_patches` selections within one
  configured subscription and target ARM prefix; reject AKS.
- Invoke one pre-created HTTPS SRE Agent trigger with a fresh API UAI
  managed-identity token, an independently configured exact agent-origin pin,
  disabled redirects, and no operator-token forwarding.
- Accept only HTTP `202`, `success=true`, and a non-empty `threadId`.
- Treat post-POST transport or malformed accepted responses as
  `submission_ambiguous` under the existing bounded retry/reconciliation
  lifecycle. SRE ambiguity never becomes ordinarily retryable at a deadline
  without a recovered thread or authoritative clean target evidence.
- Route SRE provider handles to the SRE thread data plane. Map `In Progress`,
  `Pending User Input`, and `Complete` without interpreting model prose.
- Preserve provider completion separately from patch truth. Only refreshed
  target evidence with `reconciled_clean` may complete the workflow.
- Keep trigger creation outside source-managed infrastructure; document an
  Autonomous trigger contract and enforce subscription/resource boundaries
  with adapter validation, `managedResources`, and narrowly scoped RBAC.

## Non-goals

No Azure write, trigger creation, Terraform import/refresh/plan/apply, role
mutation, deployment, commit, push, new API endpoint, or UI flow is part of
this follow-up.
