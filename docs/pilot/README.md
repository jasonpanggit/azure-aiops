# Enterprise Pilot Readiness Pack

This directory documents what is required, verified, and owned to run
AIOps Operations Graph (HOG) as a controlled enterprise pilot across real
Azure subscriptions. It complements, and does not duplicate, the existing
runbooks under `docs/` for individual intelligence engines (patch,
vulnerability, network, lifecycle, remediation, incident causality, ontology)
and `docs/PRODUCTION_RUNTIME_ACTIVATION.md` for deployment configuration.

| Document | Covers |
| --- | --- |
| [`OBSERVABILITY.md`](OBSERVABILITY.md) | Platform telemetry, availability, provider health, discovery freshness, alerting. |
| [`RELIABILITY.md`](RELIABILITY.md) | SLOs, timeouts, retries, circuit breakers, degradation modes, backup/restore/DR. |
| [`SECURITY.md`](SECURITY.md) | Entra auth, RBAC, scope enforcement, SPN governance, Key Vault, network isolation, secret rotation. |
| [`CICD.md`](CICD.md) | Build/test/scan pipeline, deployment, environment promotion, rollback, versioning, config validation. |
| [`DATA_GOVERNANCE.md`](DATA_GOVERNANCE.md) | Provenance, retention, residency, access control, audit, deletion, freshness, customer isolation. |
| [`SUPPORT_MODEL.md`](SUPPORT_MODEL.md) | RACI, runbook index, troubleshooting, escalation, incident response, known limitations. |
| [`ONBOARDING_GUIDE.md`](ONBOARDING_GUIDE.md) | Pilot onboarding, architecture summary, prerequisites, demo script, acceptance criteria, feedback plan, exit criteria. |
| [`READINESS_REVIEW.md`](READINESS_REVIEW.md) | Production/security/performance/UX/customer-value validation checklist with evidence. |

## How to use this pack

1. A pilot **owner** (see `SUPPORT_MODEL.md` RACI) walks `READINESS_REVIEW.md`
   end to end before the first real subscription is onboarded, and records
   evidence for every checklist row.
2. `ONBOARDING_GUIDE.md` is handed to the pilot customer/team; it assumes no
   prior context beyond "we're piloting an AIOps workbench."
3. `SUPPORT_MODEL.md` is what the on-call/support rotation references during
   the pilot; it links out to the per-engine runbooks rather than repeating
   them.
4. `OBSERVABILITY.md`, `RELIABILITY.md`, `SECURITY.md`, `CICD.md`, and
   `DATA_GOVERNANCE.md` are the technical backing for the corresponding rows
   in `READINESS_REVIEW.md`.

## Scope boundary

This pack governs the **platform** (API, web workbench, provider runtime,
CI/CD, infrastructure). It does not restate customer-specific compliance
policy packs (`docs/architecture.md`, the Compliance workspace's policy
model) or per-engine algorithmic behavior (the engine-specific `*_RUNBOOK.md`
files) — those are referenced, not duplicated.
