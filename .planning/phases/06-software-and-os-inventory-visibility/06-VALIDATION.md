---
phase: 06-software-and-os-inventory-visibility
slug: software-and-os-inventory-visibility
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-25
---

# Phase 06 — Validation Strategy

> Per-phase Nyquist validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest; Vitest + React Testing Library + jsdom |
| **Config file** | `pyproject.toml`; `web/vitest.config.ts` |
| **Quick run command** | `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` |
| **Full suite command** | `uv run pytest -q && (cd web && npm test)` |
| **Estimated runtime** | ~60 seconds for focused checks; repository-dependent for full suites |

---

## Sampling Rate

- **After every task commit:** Run the task-specific command in the Per-Task Verification Map. For UI tasks, include the co-located page test; for the decision checkpoint, verify the selected provider configuration before continuing.
- **After every plan wave:** Run `uv run pytest -q && (cd web && npm test)`.
- **Before `/gsd-verify-work`:** Run the full backend and web suites, `uv run ruff check src tests`, `cd web && npm run lint`, and `cd web && npm run build`.
- **Max feedback latency:** 60 seconds for focused task checks.

## Wave Sampling

| Wave | Plans | Required sample after wave |
|------|-------|-----------------------------|
| 1 | 06-01 | OS provider/API tests plus Software Inventory page test |
| 2 | 06-02 | ARG client, incremental-generation, and inventory provider tests |
| 3 | 06-03 | Logs client, canonical current-state, exact join, API, and page tests |
| 4 | 06-04 | Workspace/runtime/source-status tests |
| 5 | 06-05 | EOL repository/review/API/page tests |
| 6 | 06-06 | EOL adapter, API, OneLake document tests plus blocking provider decision |
| 7 | 06-07 | Mapping repository/provider/API/page tests |
| 8 | 06-08 | Narrative/provider/API/page tests |
| 9 | 06-09 | Full backend suite, full web suite, lint, and build |

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 06-01 | 1 | INV-01/02/05/06 | T-06-01/02 | Scope before aggregation and server-validated detail | API + UI | `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-01-02 | 06-01 | 1 | INV-01/05 | T-06-03/04 | Failed source is not successful empty; native uncertainty is explicit | API | `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` | W0/task | ⬜ pending |
| 06-02-01 | 06-02 | 2 | INV-01/02/05 | T-06-05/07 | Fixed native query and honest image/version separation | Unit + integration | `uv run pytest tests/test_inventory_provider.py tests/test_incremental_sync.py -q` | W0/task | ⬜ pending |
| 06-02-02 | 06-02 | 2 | INV-01/02/05 | T-06-05/06/08 | Independent native/Arc failure and exact source identity | Unit + integration | `uv run pytest tests/test_inventory_provider.py tests/test_incremental_sync.py tests/test_azure_clients.py -q` | W0/task | ⬜ pending |
| 06-03-01 | 06-03 | 3 | INV-01/02/05 | T-06-09/10/11 | Logs boundary, exact joins, scope-first grouping, bounded parser | API + UI | `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-03-02 | 06-03 | 3 | INV-01/02/05 | T-06-09/11/12 | One current row per exact machine/canonical identity and explicit environment | Unit + API | `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` | W0/task | ⬜ pending |
| 06-04-01 | 06-04 | 4 | INV-01/02/05 | T-06-13/14/16 | Workspace is server-owned and publication is atomic | Integration | `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_runtime.py -q` | W0/task | ⬜ pending |
| 06-04-02 | 06-04 | 4 | INV-01/05 | T-06-14/15 | Refresh failure, stale, partial, unavailable, and empty success differ | Integration | `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_runtime.py -q` | W0/task | ⬜ pending |
| 06-05-01 | 06-05 | 5 | INV-03 | T-06-17/18/19 | Explicit confirmation, auth, exact key, and revision protection | API + UI | `uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-05-02 | 06-05 | 5 | INV-03 | T-06-17/18/20 | Scoped candidates and durable review provenance | API | `uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py -q` | W0/task | ⬜ pending |
| 06-06-01 | 06-06 | 6 | INV-03 | T-06-21/22 | HTTPS allowlist, redirect/size/time bounds, claim extraction, failure isolation | Adapter + API | `uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py -q` | W0/task | ⬜ pending |
| 06-06-02 | 06-06 | 6 | INV-03 | T-06-23 | Human selects approved web/LLM provider and non-secret config contract | Blocking decision | `checkpoint:decision — provider selection and configuration contract required before Task 06-06-03` | N/A | ⬜ pending |
| 06-06-03 | 06-06 | 6 | INV-03 | T-06-23/24 | Bounded AI lookup, all candidates, atomic restart-safe catalog | API + integration | `uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py tests/test_onelake_documents.py -q` | W0/task | ⬜ pending |
| 06-07-01 | 06-07 | 7 | INV-02/05 | T-06-26/27/28/29 | Scope-checked explicit mapping decision with audit | API + UI | `uv run pytest tests/test_inventory_mapping.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-07-02 | 06-07 | 7 | INV-02/05 | T-06-26/27/28/29 | Rejection/conflict/isolation and unapproved-count exclusion | API + UI | `uv run pytest tests/test_inventory_mapping.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-08-01 | 06-08 | 8 | INV-04/05 | T-06-30/31/32 | Aggregate-only scoped narration and fact fallback | API + UI | `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-08-02 | 06-08 | 8 | INV-04/05 | T-06-30/31/32/33 | Bounded, cited, non-mutating narrative failure states | API + UI | `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q && cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-09-01 | 06-09 | 9 | INV-05/06 | T-06-34/36/37 | One route/two tabs with API scope and visible source trust | UI | `cd web && npm run test -- src/app/software-inventory/page.test.tsx` | W0/task | ⬜ pending |
| 06-09-02 | 06-09 | 9 | INV-05/06 | T-06-34/35/36 | Scoped safe CSV and final UI/API state matrix | UI + API | `cd web && npm run test -- src/lib/csv.test.ts src/app/software-inventory/page.test.tsx && cd .. && uv run pytest tests/test_api_inventory_router.py -q` | W0/task | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_inventory_provider.py` — OS/software normalization, exact joins, canonical latest-state selection, environment, grouping, and source status.
- [ ] `tests/test_api_inventory_router.py` — scope, envelopes, pagination, EOL review, mapping mutations, narrative fallback, and failure states.
- [ ] `tests/test_logs_client.py` — `tables`/`columns`/`rows`, HTTP failures, malformed schema, workspace bounds, and response limits.
- [ ] `tests/test_inventory_eol.py` — catalog/review persistence, all adapters, bounded official scraping, citations, and revision conflicts.
- [ ] `tests/test_inventory_mapping.py` — server-owned mapping approval/rejection, provenance, audit, scope, and optimistic revision.
- [ ] `tests/fixtures/mock_inventory_arg.json` and `tests/fixtures/mock_configurationdata.json` — source-family, representation-change, environment, exact-join, and failure fixtures.
- [ ] `web/src/app/software-inventory/page.test.tsx` and `web/src/lib/csv.test.ts` — two tabs, summaries, filters, badges, drill-down, review actions, fallback states, and safe export.

No package installation is required; use the existing pytest/Vitest infrastructure and standard-library or already-approved HTTP/content parsing.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Authenticated Azure-backed OS and software walkthrough | INV-01/05 | Local fixtures do not prove tenant permissions, real workspace mapping, or provider freshness | With approved credentials and configured subscriptions/workspaces, open both tabs, verify source status/evidence, exact machine joins, environment values, and a provider outage state. |
| Official-vendor citation review | INV-03 | Human must confirm citations point to the intended official product lifecycle page | Trigger an unmapped OS review, compare every candidate URL/claim/retrieval time, and confirm only the selected candidate/manual date persists. |
| Responsive and keyboard inventory workflow | INV-06 | jsdom tests cannot establish real viewport layout or browser focus behavior | Check desktop/tablet/mobile widths, keyboard tab/drill-down/review actions, source warnings, and CSV download. |

---

## Validation Sign-Off

- [ ] All auto tasks have the mapped automated command; the decision checkpoint is completed before its dependent task.
- [ ] Sampling continuity: no three consecutive tasks without automated verification.
- [ ] Wave 0 covers all phase-specific test and fixture references.
- [ ] No watch-mode flags are used.
- [ ] Focused feedback latency is under 60 seconds.
- [ ] `nyquist_compliant: true` set only after execution validation confirms the map.

**Approval:** pending
