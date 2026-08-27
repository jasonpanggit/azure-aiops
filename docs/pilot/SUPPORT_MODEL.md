# Support Model

## RACI

| Activity | Responsible | Accountable | Consulted | Informed |
| --- | --- | --- | --- | --- |
| Pilot go/no-go decision | Platform lead | Product owner | Security reviewer, pilot customer sponsor | Support rotation |
| Day-to-day on-call / alert triage | Support rotation (see below) | Platform lead | Engine owners (per `*_RUNBOOK.md`) | Product owner |
| Subscription/tenant onboarding | Onboarding engineer | Platform lead | Security reviewer (SPN scope review) | Support rotation |
| Ontology/Fabric publication incidents | Platform lead | Platform lead | Fabric admin | Support rotation, pilot customer |
| Remediation plan approval (CAB) | Business service owner (per `docs/pilot/DATA_GOVERNANCE.md`) | Business service owner | Platform lead, security reviewer | Support rotation |
| Security incident (SPN compromise, data exposure) | Security reviewer | Platform lead | Legal/compliance (if applicable) | Pilot customer sponsor |
| Post-incident review | Platform lead | Platform lead | Everyone involved in the incident | Product owner, pilot customer |

Fill in named individuals per pilot deployment; this table defines roles, not
people, so it survives staffing changes.

## Runbook index

Per-engine operational runbooks already exist and are the primary reference
during an incident — this document does not duplicate them:

| Runbook | Covers |
| --- | --- |
| `docs/OPERATIONS_AGENT_RUNBOOK.md` | Operations Copilot / Foundry agent operational procedures |
| `docs/SEMANTIC_RUNBOOK.md` | Semantic Knowledge Layer operations |
| `docs/ONTOLOGY_RUNBOOK.md` | Fabric ontology publication, rollback, reactivation |
| `docs/FABRIC_RUNBOOK.md` | Fabric dataset/table sync operations |
| `docs/NETWORK_INTELLIGENCE.md` | Network engine operations |
| `docs/VULNERABILITY_INTELLIGENCE.md` | Vulnerability engine operations |
| `docs/PATCH_INTELLIGENCE_RUNBOOK.md` | Patch intelligence operations |
| `docs/LIFECYCLE_INTELLIGENCE_RUNBOOK.md` | Lifecycle intelligence operations |
| `docs/CHANGE_INTELLIGENCE_RUNBOOK.md` | Change intelligence operations |
| `docs/INCIDENT_CAUSALITY_RUNBOOK.md` | Incident causality engine operations |
| `docs/REMEDIATION_PLANNING_RUNBOOK.md` | Remediation planning engine operations |
| `docs/PREDICTIVE_OPERATIONS_RUNBOOK.md` | Predictive operations engine operations |
| `docs/pilot/RELIABILITY.md` (this pack) | Platform-level degradation modes, backup/DR |
| `docs/pilot/OBSERVABILITY.md` (this pack) | Alert definitions and what they mean |

## Troubleshooting quick reference

| Symptom | First check | Likely cause | Reference |
| --- | --- | --- | --- |
| `/ready` returns 503 | `GET /health` — which provider is not `ready` | Upstream discovery/ontology/enrichment source down or stale | `OBSERVABILITY.md`, provider-specific runbook |
| Copilot answers "narration unavailable" | Foundry circuit breaker state (`FoundryCircuitOpenError` in logs) | Foundry endpoint unreachable or repeatedly erroring | `RELIABILITY.md` §Foundry Copilot calls |
| A subscription's data looks stale | `GET /api/v1/connections/{id}/health` | Discovery SPN auth failure, or ARG throttling | `docs/PRODUCTION_RUNTIME_ACTIVATION.md`, `DATA_SOURCES.md` |
| A user sees no data / empty investigation | Confirm their grant's scope in `HERMES_API_GATEWAY_GRANTS` | Scope narrowing is working as designed — check grants, not a bug | `SECURITY.md` |
| Saved investigation disappeared | Ask whether browser data/`localStorage` was cleared | Client-side-only persistence (known gap) | `DATA_GOVERNANCE.md` |
| Deployment fails at container startup | Container App revision logs — `akv_bootstrap` failures fail loudly | Malformed `HERMES_AKV_BOOTSTRAP_SECRETS` or missing Key Vault RBAC | `src/api/akv_bootstrap.py`, `SECURITY.md` |

## Escalation path

1. **On-call/support rotation** triages using the table above and the linked
   runbook.
2. If unresolved within the pilot's agreed response SLA (recommend: 1 hour
   for a `/ready` outage, 4 hours for a degraded-but-serving provider),
   escalate to the **platform lead**.
3. Security-flavored incidents (suspected SPN compromise, unexpected
   cross-scope data exposure, Key Vault access anomaly) escalate directly to
   the **security reviewer**, bypassing the standard triage queue — see
   Incident Response below.
4. The **pilot customer sponsor** is informed of any incident affecting
   their data or availability, per the communication cadence agreed in
   `ONBOARDING_GUIDE.md`.

## Incident response

For a **platform** incident (this repo's own reliability, not a customer's
Azure environment — that flows through the Incident Command Workspace
instead):

1. Declare: on-call opens a tracking issue, sets severity, pages the
   platform lead if severity ≥ 2.
2. Contain: for a security incident, disable the affected
   `SubscriptionConnection` (soft-deletes/retires its data reach) and/or
   rotate the implicated Key Vault secret immediately.
3. Communicate: initial notification to the pilot customer sponsor within
   the agreed window (recommend 30 minutes for a severity-1).
4. Resolve: apply the fix per the relevant runbook; verify via `/health`
   and `/ready` before declaring resolved.
5. Post-incident review: platform lead runs a blameless review within 5
   business days; findings feed back into `READINESS_REVIEW.md` and this
   support model.

## Known limitations (disclose to pilot customers)

- Saved investigations, remediation plans, and compliance exceptions persist
  in browser `localStorage`, not server-side — they do not survive a
  browser data clear and are not shared across devices/users.
- Multi-agent investigation ledgers are in-memory only, bounded to the most
  recent 1,000 entries; they do not survive an API process restart.
- No per-request allow-side audit log exists yet (only denial counts are
  recorded) — see `DATA_GOVERNANCE.md`.
- No single documented full-tenant-offboarding/right-to-be-forgotten runbook
  exists yet — offboarding today is "disable connection(s) + separately
  purge the OneLake generation."
- Foundry tool latency is not yet exported as a dedicated OTel histogram
  (only circuit-breaker failure counts are tracked in-process).
- Frontend Real User Monitoring is not yet wired to Application Insights.

These are the same gaps already called out in `RELIABILITY.md`,
`DATA_GOVERNANCE.md`, and `OBSERVABILITY.md` — listed together here so
support staff have one place to point a customer asking "is X durable?".
