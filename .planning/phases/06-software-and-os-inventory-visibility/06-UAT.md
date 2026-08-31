---
status: complete
phase: 06-software-and-os-inventory-visibility
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md, 06-04-SUMMARY.md, 06-05-SUMMARY.md, 06-06-SUMMARY.md, 06-07-SUMMARY.md, 06-08-SUMMARY.md, 06-09-SUMMARY.md]
started: 2026-08-31T13:28:33Z
updated: 2026-08-31T13:28:33Z
---

## Current Test

[testing complete]

## Tests

### 1. Authorized collection returns grouped OS rows with effective scope and per-source status.
expected: Authorized collection returns grouped OS rows with effective scope and per-source status.
result: pass
source: automated

### 2. Validated group detail returns exact Azure VM and Arc resource rows with evidence and environment.
expected: Validated group detail returns exact Azure VM and Arc resource rows with evidence and environment.
result: pass
source: automated

### 3. Software Inventory route renders real OS response data, source warnings, review-required state, and keyboard-reachable drill-down.
expected: Software Inventory route renders real OS response data, source warnings, review-required state, and keyboard-reachable drill-down.
result: pass
source: automated

### 4. Native VM and Arc OS observations are independently acquired, normalized, and published in one immutable generation.
expected: Native VM and Arc OS observations are independently acquired, normalized, and published in one immutable generation.
result: pass
source: automated

### 5. Generated machine rows preserve exact identity, source evidence, tag-derived environment, and honest native version uncertainty.
expected: Generated machine rows preserve exact identity, source evidence, tag-derived environment, and honest native version uncertainty.
result: pass
source: automated

### 6. Bounded Logs Query API parsing accepts typed ConfigurationData tables and distinguishes valid empty data from malformed, failed, or oversized responses.
expected: Bounded Logs Query API parsing accepts typed ConfigurationData tables and distinguishes valid empty data from malformed, failed, or oversized responses.
result: pass
source: automated

### 7. Canonical installed-software observations deduplicate representation/version history and preserve exact linked or explicitly unlinked machine context.
expected: Canonical installed-software observations deduplicate representation/version history and preserve exact linked or explicitly unlinked machine context.
result: pass
source: automated

### 8. Configured Log Analytics workspaces feed canonical, exact-joined software observations through immutable publication.
expected: Configured Log Analytics workspaces feed canonical, exact-joined software observations through immutable publication.
result: pass
source: automated

### 9. Workspace omission, successful empty results, partial access, degraded failure, and last-known-row retention remain distinct.
expected: Workspace omission, successful empty results, partial access, degraded failure, and last-known-row retention remain distinct.
result: pass
source: automated

### 10. Runtime reads generation metadata and marks an old inventory generation stale without erasing its observations.
expected: Runtime reads generation metadata and marks an old inventory generation stale without erasing its observations.
result: pass
source: automated

### 11. A catalog miss returns all valid multi-source EOL candidates with bounded citation and extraction provenance.
expected: A catalog miss returns all valid multi-source EOL candidates with bounded citation and extraction provenance.
result: pass
source: automated

### 12. Only an authenticated, operated, scoped, exact-key, revision-checked candidate/manual confirmation persists lifecycle data.
expected: Only an authenticated, operated, scoped, exact-key, revision-checked candidate/manual confirmation persists lifecycle data.
result: pass
source: automated

### 13. The OS page exposes review-required state, every candidate field/citation, explicit candidate/manual confirmation, and refresh behavior.
expected: The OS page exposes review-required state, every candidate field/citation, explicit candidate/manual confirmation, and refresh behavior.
result: pass
source: automated

### 14. Bounded official-vendor retrieval extracts date claims with HTTPS allowlisting, citations, and typed failures.
expected: Bounded official-vendor retrieval extracts date claims with HTTPS allowlisting, citations, and typed failures.
result: pass
source: automated

### 15. All configured source candidates are returned concurrently without an automatic winner, with explicit unavailable external-provider state.
expected: All configured source candidates are returned concurrently without an automatic winner, with explicit unavailable external-provider state.
result: pass
source: automated

### 16. Deterministic normalization preserves raw software identity while approved mappings canonicalize aggregate grouping.
expected: Deterministic normalization preserves raw software identity while approved mappings canonicalize aggregate grouping.
result: pass
source: automated

### 17. Authenticated, scoped mapping list, approval, and rejection routes enforce optimistic revisions and audit provenance.
expected: Authenticated, scoped mapping list, approval, and rejection routes enforce optimistic revisions and audit provenance.
result: pass
source: automated

### 18. Malformed model output remains a non-authoritative, provenance-bearing suggestion.
expected: Malformed model output remains a non-authoritative, provenance-bearing suggestion.
result: pass
source: automated

### 19. Scoped inventory endpoint returns deterministic facts with source status, evidence citations, confidence, and a visible Foundry-unavailable warning.
expected: Scoped inventory endpoint returns deterministic facts with source status, evidence citations, confidence, and a visible Foundry-unavailable warning.
result: pass
source: automated

### 20. Only bounded scope-filtered aggregate facts are sent to Foundry, with unsupported citations excluded.
expected: Only bounded scope-filtered aggregate facts are sent to Foundry, with unsupported citations excluded.
result: pass
source: automated

### 21. OS and exact software/version drill-down tables show affected machines with authorized scope, source, environment, identity, resource, timestamp, and evidence context.
expected: OS and exact software/version drill-down tables show affected machines with authorized scope, source, environment, identity, resource, timestamp, and evidence context.
result: pass
source: automated

### 22. Software detail CSV export includes canonical/raw identity and environment/resource context and protects spreadsheet-sensitive values.
expected: Software detail CSV export includes canonical/raw identity and environment/resource context and protects spreadsheet-sensitive values.
result: pass
source: automated

### 23. Operator visually confirms the authenticated browser route and source/evidence presentation.
expected: Operator visually confirms the authenticated browser route and source/evidence presentation.
result: pass

### 24. Operators can inspect family-specific source degradation while successful inventory remains available.
expected: Operators can inspect family-specific source degradation while successful inventory remains available.
result: pass

### 25. Authorized operators can view grouped canonical software/version rows and exact detail rows in the Installed Software tab with source and join warnings.
expected: Authorized operators can view grouped canonical software/version rows and exact detail rows in the Installed Software tab with source and join warnings.
result: pass

### 26. Authenticated UI/API walkthrough of healthy and failed workspace refresh states.
expected: Authenticated UI/API walkthrough of healthy and failed workspace refresh states.
result: pass

### 27. Authenticated browser walkthrough confirms candidate inspection, persistence after refresh, and stale-revision feedback.
expected: Authenticated browser walkthrough confirms candidate inspection, persistence after refresh, and stale-revision feedback.
result: pass

### 28. Operator confirmation persists the seeded catalog, provenance, audit event, and revision-safe selection across restart.
expected: Operator confirmation persists the seeded catalog, provenance, audit event, and revision-safe selection across restart.
result: pass

### 29. The Software Inventory page exposes server-owned mapping review actions and sends the current revision.
expected: The Software Inventory page exposes server-owned mapping review actions and sends the current revision.
result: pass

### 30. Software Inventory renders fact-only narrative state, model/fact separation, source badges, dashboard views, filters, and drill-down controls.
expected: Software Inventory renders fact-only narrative state, model/fact separation, source badges, dashboard views, filters, and drill-down controls.
result: pass

### 31. Discoverable Software Inventory route with exactly two accessible tabs, dashboard summaries/charts, filters, lifecycle badges, and source states.
expected: Discoverable Software Inventory route with exactly two accessible tabs, dashboard summaries/charts, filters, lifecycle badges, and source states.
result: pass

### 32. Inventory UI remains responsive and production-buildable.
expected: Inventory UI remains responsive and production-buildable.
result: pass

## Summary

total: 32
passed: 32
issues: 0
skipped: 0
blocked: 0

## Gaps

[none]
