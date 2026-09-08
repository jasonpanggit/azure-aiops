---
phase: 13
slug: autonomous-ontology-discovery-and-fabric-synchronization
status: verified
threats_open: 0
asvs_level: 1
created: 2026-09-08
---

# Phase 13 — Security

> Per-phase security contract for the integrated Phase 13 implementation.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| API and UI → command intake | Authenticated, scope-bound lifecycle and maintenance requests enter durable state machines. | Scoped identifiers, expected revisions, idempotency keys |
| Coordinator → curator and dispatch | The coordinator reads bounded evidence and creates typed dispatch records without publication authority. | Sanitized evidence, proposal and dispatch hashes |
| Publisher → OneLake and Fabric | A distinct managed identity materializes validated generations and performs fenced pointer changes. | Immutable generations, ETags, fences, receipts |
| Deployer → Container Apps Jobs | Deployment authority may start named fixed templates; runtime identities cannot start or override Jobs. | Template hashes, execution status |
| Evidence collector → retained artifacts | Cloud observations are reduced to closed statuses, counts, times, and opaque hashes. | Sanitized evidence only |
| Model output → authoritative ontology | Prompt and tool output crosses strict parsing, deterministic policy, review, and hard-shadow admission. | Bounded proposals; no direct authoritative writes |

## Threat Register

The 94 authored STRIDE entries in Plans 13-01 through 13-21 were audited at
ASVS L1. Threat IDs remain authoritative in their plan files; this table records
the closure evidence by implementation boundary without duplicating the full
register.

| Threat group | Category | Component | Severity | Disposition | Mitigation | Status |
|--------------|----------|-----------|----------|-------------|------------|--------|
| T13-PF, T13-01–12, T13-C1/C2, T13-D1, T13-E1/E2 | STRIDE | Core lifecycle, scope, shadow admission, evaluation, publication, rollback | critical–medium | mitigate | Deterministic identity, scope-first lookup, bounded batches, strict parsing, CAS/fences, immutable receipts, hard-shadow exclusion, and rollback invariance with focused tests. | closed |
| T13-G16-01–09 | STRIDE | OneLake coordinator, reconciliation, curator, maintenance, dispatch | critical–medium | mitigate | Storage-returned ETags, distinct roots/capabilities, typed reauthorization, bounded evidence and retries, credential redaction, and durable dispatch tests. | closed |
| T13-G17-01–10 | STRIDE | Dedicated publisher and guarded rollback drills | critical–high | mitigate | Publisher-specific identity, immutable commands, monotonic fences, five-consumer checks, newer-fence rollback, closed failures, and one-shot drill controls. | closed |
| T13-G18-01–07 | STRIDE | API/UI command topology | critical–medium | mitigate | Separate authorization dependencies, scope-before-lookup, deterministic command identity, durable status, dedicated maintenance grant, and exact capability-matrix tests. | closed |
| T13-G19-01–09 | STRIDE | Fixed validation deployment and fixtures | critical–medium | mitigate | Exact plan allowlist, zero replace/destroy gate, fixed templates, no runtime Job-start grants, server-owned three-record fixture, owner/fence cleanup, TTL sweep, and sanitized deployment evidence. | closed |
| T13-G20-01–09 | STRIDE | Direct deployed lifecycle evidence | critical–medium | mitigate | Ordered resumable state machine, isolated credentials, fixed starts, template/root/tag hashes, direct receipt derivation, forbidden-value scan, and fail-closed missing-evidence handling. | closed |
| T13-G21-01–09 | STRIDE | Final deployed audit | critical–high | mitigate | Authenticated non-local audit contracts, cross-source hashes, effective-role expansion, no-override receipts, immutable cleanup evidence, and hard rejection of local substitution. | closed |
| T13-SC | Tampering | Existing locked dependencies | low | accept | No new package installation was required; committed lockfiles and repository dependency policy remain authoritative. | closed |

Implementation closure does not promote the feature. The deployed lifecycle
artifact still reports `BLOCKED/PENDING` because retry-rotation and complete
publication/rollback observations are unavailable. The validator records that
absence as failure and exposes no activation interface, so the evidence gap
cannot become a privilege or publication bypass.

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-13-01 | T13-SC | Phase 13 used the repository's existing locked dependencies and introduced no unreviewed package source. | Phase plan | 2026-09-08 |

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-08 | 94 | 94 | 0 | Copilot direct fallback after auditor file-access failure |

## Sign-Off

- [x] All threats have a disposition.
- [x] Accepted risks are documented.
- [x] `threats_open: 0` confirmed.
- [x] `status: verified` set in frontmatter.

**Approval:** verified 2026-09-08
