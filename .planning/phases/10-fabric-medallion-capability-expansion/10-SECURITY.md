---
phase: 10
slug: fabric-medallion-capability-expansion
status: verified
threats_open: 0
asvs_level: 1
created: 2026-09-02
---

# Phase 10 - Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Deployed API/web -> Fabric workspace and OneLake | Authenticated app runtime reads and publishes governed medallion metadata using configured Fabric auth. | Operational inventory, metadata source status, publication state, quality reports |
| Authenticated caller -> `/api/v1/fabric-medallion/*` | Medallion APIs expose read-only, scope-enforced operational metadata through existing envelope/auth patterns. | Layer health, manifest entries, governance gap counts, capacity/maintenance/lineage summaries |
| Gold grounding / Data Agent -> deterministic semantic and inventory context | AI-facing grounding must cite curated Gold evidence, respect scope, and defer to inventory for resource identity conflicts. | Gold evidence, citations, deterministic fallback context |
| Live validation tooling -> dev Fabric workspace and deployed endpoints | Phase validation reads live Fabric/API/web state and records real degraded outcomes without fabricating passes. | Reconciliation results, endpoint health, evaluation baseline metrics |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-10-01-01 | Information Disclosure | Deploy/config artifacts | high | mitigate | Deployed Fabric config uses managed identity and contains no stored client secret. | closed |
| T-10-01-02 | Denial of Service | Existing working-tree dependency | low | accept | Non-blocking planning risk; tracked as accepted because execution preserved existing user work rather than resetting. | closed |
| T-10-01-03 | Repudiation | Existing dirty state | low | accept | Non-blocking planning risk; accepted as a documentation-only provenance limitation for inherited work. | closed |
| T-10-02-01 | Tampering | Data quality governance | medium | mitigate | Ownership/tag gaps are counted and surfaced by data-quality validation instead of silently passing. | closed |
| T-10-02-02 | Tampering | Ontology publication | medium | mitigate | Referential-integrity checks reject dangling/self/duplicate relationships. | closed |
| T-10-03-01 | Information Disclosure | Telemetry | medium | mitigate | Gold/Fabric telemetry records low-cardinality degraded attributes and truncated reasons only. | closed |
| T-10-03-02 | Denial of Service | Fabric publication retry | medium | mitigate | Fabric client/publisher retry behavior remains bounded and visible. | closed |
| T-10-04-01 | Spoofing | Medallion health | high | mitigate | Dataset health prioritizes unavailable/failed over healthy-empty so missing data is not reported healthy. | closed |
| T-10-04-02 | Repudiation | Freshness SLO tuning | low | accept | Per-environment freshness tuning remains an accepted non-blocking configuration risk. | closed |
| T-10-05-01 | Repudiation | Publication manifest | medium | mitigate | Retired projections require explicit retirement evidence in the publication manifest. | closed |
| T-10-05-02 | Elevation of Privilege | Publication manifest API | high | mitigate | Manifest exposure is GET-only and read-only through the medallion router. | closed |
| T-10-06-01 | Tampering | Change-domain ontology rows | high | mitigate | Change rows enter the same ontology synchronization/validation path as all other rows. | closed |
| T-10-06-02 | Repudiation | Predictive/remediation disposition audit | medium | mitigate | Regression evidence records the disposition outcome instead of assuming coverage. | closed |
| T-10-06-03 | Tampering | Incident-domain ontology rows | high | mitigate | Incident rows enter ontology synchronization before validation, with no bypass. | closed |
| T-10-07-01 | Elevation of Privilege | OneLake data access roles | high | mitigate | Data-access role helper exposes read-only list/get behavior only. | closed |
| T-10-07-02 | Spoofing | Fabric capacity health | high | mitigate | Paused capacity maps to unavailable, not healthy. | closed |
| T-10-07-03 | Elevation of Privilege | Delta table maintenance | medium | mitigate | Maintenance helper reads last known status only and exposes no trigger operation. | closed |
| T-10-07-04 | Information Disclosure | Lineage | medium | mitigate | Lineage output is summarized and scoped; native deep links are explicit. | closed |
| T-10-08-01 | Tampering | Historical retention | medium | mitigate | History-preserving write modes are allow-listed for trend tables with regression coverage. | closed |
| T-10-09-01 | Tampering | Staged rollout | high | mitigate | Rollout flags and live validation prevent undispositioned missing tables from being treated as success. | closed |
| T-10-09-02 | Repudiation | Missing table disposition | medium | mitigate | Reconciliation emits dispositions and `expected_missing_undispositioned`. | closed |
| T-10-10-01 | Spoofing | Semantic model readiness | high | mitigate | Semantic model deployment failures map to explicit `deployment-blocked` readiness. | closed |
| T-10-10-02 | Tampering | Semantic serving definition | high | mitigate | Semantic model definitions reference curated Gold tables and do not replace inventory identity authority. | closed |
| T-10-11-01 | Tampering | Gold-grounding citations | critical | mitigate | Gold grounded findings require at least one citation. | closed |
| T-10-11-02 | Elevation of Privilege | Gold-grounding resource scope | critical | mitigate | Gold citations require scoped `/subscriptions/` ARM resource IDs. | closed |
| T-10-11-03 | Information Disclosure | Gold-grounding telemetry | medium | mitigate | Telemetry records low-cardinality query/degraded metadata only. | closed |
| T-10-12-01 | Tampering | Degraded Gold grounding | critical | mitigate | Gold unavailability degrades to deterministic ontology context rather than fabricated evidence. | closed |
| T-10-12-02 | Tampering | Relationship suggestions | critical | mitigate | Deterministic relationships win over conflicting suggestions. | closed |
| T-10-12-03 | Spoofing | Inventory authority | critical | mitigate | Gold citations are cross-checked against inventory identity/lifecycle before narration. | closed |
| T-10-13-01 | Elevation of Privilege | Medallion API | high | mitigate | Fabric medallion router is GET-only with no mutation decorators. | closed |
| T-10-13-02 | Spoofing | Governance API | medium | mitigate | Governance route returns gap counts and evidence, not synthesized ownership. | closed |
| T-10-13-03 | Elevation of Privilege | Capabilities API | high | mitigate | Capabilities route reads maintenance/capacity/role state and does not trigger maintenance or mutations. | closed |
| T-10-14-01 | Information Disclosure | Web UI rendering | low | accept | Low-severity display-only residual risk accepted; no blocking security gate impact. | closed |
| T-10-14-02 | Denial of Service | Web medallion panel | medium | mitigate | Web tests cover independent section degradation so one failed panel does not blank the experience. | closed |
| T-10-15-01 | Repudiation | Evaluation baseline | high | mitigate | Real baseline artifact records degraded metrics as-is: 23 cases, 0 errors, 0 timeouts, 20/23 routing pass. | closed |
| T-10-15-02 | Denial of Service | Live validation | high | mitigate | Validation evidence uses read-only reconciliation/API GET checks; deployment changes were explicit recovery actions, not hidden validation side effects. | closed |

*Status: open - closed - open below high threshold (non-blocking)*
*Severity: critical > high > medium > low - only open threats at or above workflow.security_block_on count toward threats_open.*
*Disposition: mitigate (implementation required) - accept (documented risk) - transfer (third-party).*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-10-01 | T-10-01-02 | Existing shared working-tree state was intentionally preserved to avoid destructive resets; low-severity provenance risk is documented. | GSD security audit | 2026-09-02 |
| AR-10-02 | T-10-01-03 | Historical dirty-state provenance cannot be fully reconstructed post hoc; summary/state artifacts capture the actual completion evidence. | GSD security audit | 2026-09-02 |
| AR-10-03 | T-10-04-02 | Freshness SLO tuning remains a configuration choice; explicit stale/aging states prevent silent success. | GSD security audit | 2026-09-02 |
| AR-10-04 | T-10-14-01 | UI display risk is low severity and bounded by existing React rendering/test coverage plus read-only API data. | GSD security audit | 2026-09-02 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-02 | 36 | 36 | 0 | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-02
