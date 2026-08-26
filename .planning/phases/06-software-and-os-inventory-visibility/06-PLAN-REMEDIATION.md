# Phase 6 Plan Verification — Remediation Report

**Status: FAIL**

## Latest Re-verification — 2026-08-25

**Status: FAIL**

### Remaining blocker

1. **[research_resolution] `06-RESEARCH.md` still has unresolved open questions.** The section is `## Open Questions` rather than `## Open Questions (RESOLVED)`, and all five questions lack inline `RESOLVED` markers. The plan-checker research-resolution gate therefore fails even though several recommendations are reflected in the plans.
   **Exact fix:** Resolve and annotate every item in `06-RESEARCH.md`: (1) record the server-owned connection-to-Log-Analytics workspace mapping and absent-configuration behavior from 06-04; (2) record the native VM explicit-unknown/review-required version policy from 06-02; (3) record the versioned server-owned catalog repository and atomic persistence choice from 06-05/06; (4) record the approved web/LLM provider/configuration decision, or explicitly close it as a blocking pre-Task-3 execution decision with the provider interface and unavailable behavior; and (5) record the existing mainstream/extended support-channel semantics from 06-05. Rename the heading to `## Open Questions (RESOLVED)` and add `RESOLVED:` text to each item. Also correct the stale validation note claiming Phase 6 requirement IDs are TBD; current ROADMAP/REQUIREMENTS define INV-01 through INV-06. Re-run plan verification after this research update.


## Historical findings from prior verification (remediated)

The five-plan package described below was the pre-remediation state. Those findings are retained as audit history; the current package now has nine numbered plans and the checks listed in the latest re-verification above.

### Prior blockers

1. **[nyquist_compliance] Missing phase validation artifact.** `06-RESEARCH.md` contains a Validation Architecture section and `.planning/config.json` enables Nyquist validation, but no `06-*-VALIDATION.md` exists. **Fix:** regenerate/create the phase validation artifact via `/gsd-plan-phase 6 --research`, then verify every task command and wave sampling entry is represented before execution.

2. **[scope_sanity] Plans 06-01, 06-02, and 06-03 exceed the hard file threshold.** They list 17, 17, and 15 modified files respectively (the 15+ threshold is a blocker), despite spanning ingestion, provider, API, UI, and tests. **Fix:** re-slice each into tracer plus expansion plans: keep the smallest end-to-end contract in the tracer, and move ARG acquisition, Logs ingestion/runtime, and EOL persistence/source adapters into separate dependent plans. Preserve the 01 → 02 → 03 ordering after re-slicing.

3. **[key_links_planned / context_compliance] D-16 has no executable approval/persistence path.** 06-04 says to store reviewable AI mapping records and require approval, but names no mapping repository, approval API, revision/concurrency contract, audit record, or UI action. Tests cannot prove a behavior that is not wired. **Fix:** add a server-owned versioned mapping store, authenticated/scope-checked list and approve/reject routes, explicit mapping revision/provenance, page approval state, and API/UI tests; keep unapproved suggestions out of group counts.

4. **[cross_plan_data_contracts] Raw-name latest selection can double-count canonical software.** 06-02 selects `arg_max` by raw `SoftwareName`; 06-04 canonicalizes later, but neither plan adds a post-canonicalization latest/dedup step keyed by exact machine identity plus canonical software identity. A machine whose reported name changes form can therefore appear twice in one canonical group. **Fix:** canonicalize before current-state selection, or add a deterministic post-normalization dedup that retains the newest row per exact machine + canonical name/version. Add a fixture/test for representation changes across timestamps and assert one current installation/detail row.

5. **[requirement_coverage / key_links_planned] The required environment context is only named at export/UI time.** 06-05 requires environment in drill-down/export columns, but 06-01/06-02 do not define how environment is derived, stored, joined, or returned. This leaves the selected exact software lookup contract (machine list with subscription/RG/environment) unverifiable. **Fix:** add an explicit environment field to the normalized machine/detail DTO, define approved tag/source precedence and an explicit Unknown value, carry it through exact joins/API responses, and test/export it.

6. **[context_compliance] D-07 official-vendor scraping is not explicit.** 06-03 says “official vendor retrieval,” which does not verify website scraping/HTML claim extraction required by the locked decision. **Fix:** specify the allowlisted HTTPS vendor fetch plus bounded HTML/content extraction, citation/claim capture, failure state, and deterministic fake/test for that adapter.

## Passing checks / notes

- All six roadmap requirements are present in plan `requirements` frontmatter and have concrete tasks.
- Plan structure is valid: all auto/tracer tasks have files, action, verify, and done fields; the decision checkpoint is valid.
- Dependency chain is acyclic and ordered: 06-01 → 06-02 → 06-03 → 06-04 → 06-05. The Phase 5 prerequisite remains a roadmap dependency and must be satisfied before execution.
- ARG/Logs boundary is correctly planned: native VM and Arc OS through separate ARG QuerySpecs; ConfigurationData through the Azure Monitor Logs Query API with workspace configuration.
- Scope, evidence, pagination, source degradation, exact `_ResourceId` joins, API-only browser access, and Phase 1 blocker avoidance are explicitly planned.
- 06-04 lists 13 files and 06-05 lists 10 files: warnings for high scope; all estimates are low-confidence because there are no completed-phase actuals.
- No `PATTERNS.md` or review artifact was present; copilot instructions contain only GSD workflow directives and are not contradicted.

Do not execute Phase 6 until the blockers are incorporated and the plans are re-verified.
