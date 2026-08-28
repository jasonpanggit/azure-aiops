---
phase: 08-fabric-migration
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/api/routers/connections.py
  - src/onboarding/service.py
  - tests/test_api_http.py
  - tests/test_subscription_onboarding.py
  - web/src/app/connections/page.tsx
  - web/src/app/connections/page.test.tsx
  - web/src/lib/types.ts
autonomous: true
requirements:
  - INV-10
  - INV-11
estimate:
  tokens: 12000
  raw_tokens: 12000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - A newly created subscription connection is validated immediately by the server and its validation result is persisted in connection health.
    - A connection whose required validation checks pass (including a degraded result caused only by optional checks) starts one asynchronous initial sync without a second operator action.
    - A required validation failure leaves the connection visible with failure details and does not start an unsafe sync.
    - The Connections page communicates validation/sync progress after creation and offers no operator action for manually invoking either lifecycle operation.
    - Existing health polling, sync failure reporting, authorization, secret redaction, and delete/edit workflows remain intact.
  artifacts:
    - src/api/routers/connections.py exposes the create response with the created detail plus validation and initial-sync state.
    - src/onboarding/service.py owns the create → validate → conditional async sync orchestration.
    - web/src/app/connections/page.tsx renders the automatic post-create operation state and retains only supported row actions.
    - Backend and frontend tests cover successful, degraded, failed-validation, and failed-sync paths.
  key_links:
    - POST /api/v1/subscription-connections calls the onboarding service orchestration after persistence and returns its operation state in the normal evidence/scope envelope.
    - The frontend uses the returned connection_id and sync_state to reuse the existing health endpoint polling path.
    - Required validation status controls whether sync_async is queued; optional-check degradation does not block sync.
---

<objective>
Automate the subscription connection lifecycle at creation: persist the connection, validate its Azure access, and queue the initial API-triggered Fabric/Hermes sync when validation permits it, while making the Connections UI communicate that lifecycle without manual Validate or Sync controls.

Purpose: Phase 08 is closed for notebook execution but explicitly retains API-server orchestration. Removing the two-step UI flow prevents connections from appearing configured while their access and Fabric-backed inventory state remain uninitialized.
Output: A tested backend create lifecycle contract and a Connections page that starts and reports the automatic validation/sync flow.
</objective>

<execution_context>
@~/.copilot/gsd-core/workflows/execute-plan.md
@~/.copilot/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@src/api/routers/connections.py
@src/onboarding/service.py
@src/onboarding/validation.py
@src/onboarding/sync.py
@web/src/app/connections/page.tsx
@web/src/lib/services.ts
@web/src/lib/types.ts

The active state says Phase 08 notebook execution is halted/closed, while API-triggered sync for connection creation, server-side orchestration, Fabric inventory/domain/ontology outputs, and user-visible status remains in scope. Preserve the existing `/validate`, `/sync`, and `/health` API contracts for compatibility; this task changes the create workflow and UI affordances, not the API-triggered orchestration boundary.
</context>

<source_audit>
| Source | Items in scope | Plan coverage |
|---|---|---|
| GOAL | Automate API-server validation and initial sync on subscription creation; report status to the user | Tasks 1-2 |
| REQ | INV-10 inventory consumers use the governed sync/read path; INV-11 identity-plane data is produced by the API-triggered sync | Task 1 |
| RESEARCH | Existing `validate`, `sync_async`, health polling, Fabric publish stages, and compatibility routes are the established path; no new dependency is needed | Tasks 1-2 |
| CONTEXT | Phase 08 remains API-triggered, notebook execution is closed, and sync status/errors must be reported to the user | Tasks 1-2 |
</source_audit>

<tasks>

<task type="tracer">
  <name>Task 1: Make connection creation validate and conditionally queue initial sync</name>
  <files>src/onboarding/service.py, src/api/routers/connections.py, tests/test_subscription_onboarding.py, tests/test_api_http.py</files>
  <action>Introduce one service-owned create lifecycle operation that first persists the connection, runs the existing full validator, persists the resulting health, and calls the existing `sync_async(connection_id, mode="initial")` only when `ValidationReport.passed` is true; optional-check degradation therefore proceeds, while any required failure remains persisted and prevents sync. Have the POST create route use that operation and return the created redacted detail together with explicit validation and initial-sync fields in the existing envelope, without exposing client secrets or changing the authorization boundary. Keep the existing standalone validate, sync, and health routes working for API compatibility. Add backend coverage with injected fake probe/ingestion behavior proving ordering, one sync queue, degraded-but-allowed behavior, required-failure behavior, response shape, secret hygiene, and existing write authorization.</action>
  <verify>
    <automated>pytest -q tests/test_subscription_onboarding.py tests/test_api_http.py</automated>
  </verify>
  <done>POST creation has one deterministic server-side lifecycle: persisted connection → validation health → conditional initial async sync; tests prove successful and degraded connections queue sync, required validation failures do not, and the response contains no secret material.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Replace manual connection lifecycle controls with automatic post-create status</name>
  <files>web/src/app/connections/page.tsx, web/src/app/connections/page.test.tsx, web/src/lib/types.ts</files>
  <behavior>
    - Creating a connection shows that validation completed and initial sync was queued, then polls `/health` using the returned connection identifier until sync succeeds or fails.
    - A required validation failure shows the server-provided validation error and does not claim that sync completed.
    - A background sync failure shows its persisted message and clears the progress indicator.
    - The connection table contains Edit and Delete actions but no manual validation or sync action.
  </behavior>
  <action>Update the create response type to represent the backend lifecycle result, consume that result in `onboard`, and reuse the existing `pollSyncState` progress presentation for the returned initial run. Display distinct success/error messages for validation and sync outcomes, refresh the list after terminal state, and retain disabled-state handling and existing edit/delete behavior. Remove the row-level Validate and Sync buttons and the corresponding `runAction` branches while leaving `connectionsApi.validate` and `connectionsApi.sync` available for non-UI API consumers. Update page mocks and tests to cover automatic creation, polling, validation failure, sync failure, and absence of the two manual controls; do not add a second client-side sync request after the server has already queued the initial run.</action>
  <verify>
    <automated>cd web && npm test -- --run src/app/connections/page.test.tsx</automated>
  </verify>
  <done>Creating a connection starts the visible automatic lifecycle from the API response, terminal health is reflected in the page, failure states are honest, and the rendered row has no manual Validate or Sync buttons.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|---|---|
| authenticated operator → connection create API | Untrusted connection identifiers, tenant/subscription IDs, credentials, and metadata enter the onboarding service |
| API server → Azure credential/access probes | Server-held credential references are resolved to perform validation and sync-scoped discovery |
| API server → Fabric/OneLake sync pipeline | A validated connection can trigger background inventory/ontology publication for one subscription |
| API response → browser | Operation state and connection metadata cross into an authenticated UI; secret material must remain redacted |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|---|---|---|---|---|---|
| T-08-01 | Tampering | `POST /subscription-connections` | high | mitigate | Reuse `WritePrincipal`, scope authorization, identifier validation, duplicate checks, and the existing service orchestration; never let the browser choose a separate sync target. |
| T-08-02 | Elevation of privilege | create-triggered validation/sync | high | mitigate | Keep sync scoped to the just-created connection and preserve the existing server-side `OperatePrincipal` behavior for standalone operational routes; the create operation must not accept arbitrary subscription lists or modes. |
| T-08-03 | Information disclosure | create response and UI state | high | mitigate | Return the existing redacted detail and sanitized validation/sync summaries; add regression assertions that submitted client secrets are absent from response text and persisted registry data. |
| T-08-04 | Denial of service | automatic background sync | medium | mitigate | Use existing `sync_async` shared executor, one generated run ID, persisted running/terminal state, and existing polling timeout; avoid synchronous Fabric work in the HTTP request. |
| T-08-05 | Repudiation | validation and sync lifecycle | medium | mitigate | Persist validation health and sync state through the existing registry operation-state path and retain the existing evidence envelope on the create response. |
| T-08-SC | Tampering | package-manager installs | low | accept | No package installation or dependency change is planned. |
</threat_model>

<verification>
Run `pytest -q tests/test_subscription_onboarding.py tests/test_api_http.py` and `cd web && npm test -- --run src/app/connections/page.test.tsx`. Confirm the backend test suite proves validation precedes sync and that required validation failures do not queue a run. Confirm the frontend test suite proves creation alone drives polling and the rendered table contains no manual Validate or Sync controls. Run the relevant TypeScript/lint check used by the repository if the frontend test setup reports type errors.
</verification>

<success_criteria>
- A single authenticated create request persists a connection, records validation health, and queues exactly one initial API-triggered sync when required checks pass.
- Required validation failures are visible and do not start sync; optional validation degradation remains explicit but does not block sync.
- The UI has no manual Validate or Sync buttons and accurately reports queued, running, succeeded, and failed automatic operations.
- Existing standalone API compatibility, scope enforcement, secret hygiene, edit/delete behavior, and health polling remain green.
</success_criteria>

<output>
Create `.planning/quick/260828-gc7-automate-subscription-connection-validat/260828-gc7-automate-subscription-connection-validat-SUMMARY.md` when done.
</output>
