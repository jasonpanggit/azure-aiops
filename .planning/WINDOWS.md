---
schema_version: 1
open_count: 17
waived_count: 0
fixed_count: 2
total_count: 19
last_updated: 2026-08-26T07:39:43.000Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01 | lint-warning | src/api/routers/multi_agent.py | 3 | Plan-level ruff includes pre-existing import formatting warning outside this plan's implementation. | open |  | 2026-08-25T13:30:54.956Z |  |
| 2 | 01 | lint-warning | src/api/routers/twin.py | 22 | Plan-level ruff includes pre-existing blind exception and Body-default warnings outside this plan's implementation. | open |  | 2026-08-25T13:30:55.020Z |  |
| 3 | 01 | lint-warning | src/hermes_arg_connector/service.py | 126 | Plan-level ruff includes pre-existing unused noqa warning outside this plan's implementation. | open |  | 2026-08-25T13:30:55.082Z |  |
| 4 | 01 | unrun-verify | .planning/phases/01-evidence-and-situation-foundation/01-PLAN.md |  | Human UI verification requiring a running local API/web fixture was not run in this non-interactive execution. | open |  | 2026-08-25T13:30:55.145Z |  |
| 5 | 01 | unrun-verify | .planning/phases/01-evidence-and-situation-foundation/01-03-PLAN.md |  | Authenticated local collection returned a successful empty envelope, so no durable detail or audit ID was available for endpoint smoke calls. | open |  | 2026-08-25T14:35:31.433Z |  |
| 6 | 01 | unrun-verify | web/src/app/situations/page.tsx |  | Desktop, tablet, and mobile visual walkthrough was not performed; automated queue/detail tests cover state transitions and keyboard reachability only. | open |  | 2026-08-25T14:35:31.497Z |  |
| 7 | 01 | deviation | scripts/start-api.sh |  | Documented uv sync --extra test omitted the API extra; local smoke required the existing locked --extra api to restore uvicorn without dependency changes. | open |  | 2026-08-25T14:35:31.560Z |  |
| 8 | 06 | stub | web/src/app/software-inventory/page.tsx | 82 | Installed Software tab is an intentional tracer placeholder until the ConfigurationData slice is connected in later Phase 6 plans. | fixed |  | 2026-08-25T15:23:57.293Z | 2026-08-25T15:43:01.297Z |
| 9 | 06 | unrun-verify | web/src/app/software-inventory/page.tsx |  | Manual browser walkthrough of /software-inventory was not run; automated page tests cover grouped rows, source warning, review flag, and drill-down. | open |  | 2026-08-25T15:24:07.515Z |  |
| 10 | 06 | unrun-verify | web/src/app/software-inventory/page.tsx |  | End-of-phase human walkthrough still required: search exact software/version and inspect linked/unlinked environment-bearing details. | open |  | 2026-08-25T15:42:50.255Z |  |
| 11 | 06 | unrun-verify | web/src/app/software-inventory/page.tsx |  | Human browser walkthrough of healthy and failed workspace refresh was not run in this non-interactive execution. | open |  | 2026-08-25T15:59:08.032Z |  |
| 12 | 06 | unrun-verify | web/src/app/software-inventory/page.tsx |  | Authenticated browser walkthrough of unknown-OS lifecycle review, candidate inspection, explicit confirmation, refresh persistence, and stale-revision conflict was not run in this non-interactive executor. | open |  | 2026-08-25T16:14:01.600Z |  |
| 13 | 06 | deviation | src/intelligence/inventory/eol_review.py |  | External web/LLM lifecycle provider remains explicitly unavailable until approved endpoint configuration is supplied. | open |  | 2026-08-25T16:25:30.658Z |  |
| 14 | 07 | unrun-verify | .planning/phases/07-unified-resource-inventory/07-06-PLAN.md |  | Authenticated browser UX Phase 7 exit walkthrough remains human verification. Live Fabric publication was partially verified by run 0bc31dd4-7965-4650-91f0-b6347c635400: ARG-backed inventory tables wrote to OneLake; LAW software inventory is tracked separately in window #18. | open |  | 2026-08-26T07:16:57.507Z |  |
| 15 | 07 | deviation | tests/test_onelake_fs.py | 257 | Full-suite run has pre-existing OneLake filesystem type assertion failure unrelated to inventory read-port changes. | open |  | 2026-08-26T07:16:57.570Z |  |
| 16 | 07 | deviation | tests/test_situations_ontology.py | 25 | Full-suite run has pre-existing situation ontology relationship assertion failure outside inventory scope. | open |  | 2026-08-26T07:16:57.635Z |  |
| 17 | 07 | deviation | tests/test_storage.py | 105 | Full-suite run has pre-existing partial-publish changedDatasets expectation failure from DatasetStore behavior outside 07-06 scope. | open |  | 2026-08-26T07:16:57.699Z |  |
| 18 | 07 | live-source-data | src/hermes_arg_connector/logs.py | 13 | Live LAW software inventory publication authenticated successfully after switching the token audience to https://api.loganalytics.io/.default, but workspace 4cf2b41b-bace-4dd6-8ec0-61c7050ed552 returned SEM0100 because the ConfigurationData table does not exist; inventory_software_observations published 0 rows and source status is degraded. | open |  | 2026-08-26T07:39:43.000Z |  |
| 19 | 07 | live-verification | infra/scripts/push_inventory_refresh_pipeline.py |  | Native Fabric DataPipeline `Inventory Refresh` verified end-to-end: on-demand Pipeline job status `Completed`, and API logs confirm `POST /api/v1/inventory/refresh` returned `200 OK`. Root cause of the earlier `datasetSettings are required for the connection 'Web'` failure was an incorrect Fabric connection type -- the script created a `"Web"` (Power Query/Dataflow) connection, but pipeline WebActivity requires a `"WebForPipeline"` connection (creation method `WebForPipeline.Contents`, parameter `baseUrl`). Fixed by recreating the connection with the correct type and switching the activity's `typeProperties` from `url` to the schema-correct `relativeUrl`. 60-minute enabled Cron schedule also confirmed present. | fixed | None -- verified working via live on-demand run and API access logs on 2026-08-26. | 2026-08-26T17:25:03.390Z | 2026-08-26T17:42:05.000Z |

````json
[
  {
    "id": 1,
    "kind": "lint-warning",
    "phase": "01",
    "file": "src/api/routers/multi_agent.py",
    "line": 3,
    "description": "Plan-level ruff includes pre-existing import formatting warning outside this plan's implementation.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T13:30:54.956Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "lint-warning",
    "phase": "01",
    "file": "src/api/routers/twin.py",
    "line": 22,
    "description": "Plan-level ruff includes pre-existing blind exception and Body-default warnings outside this plan's implementation.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T13:30:55.020Z",
    "resolved_at": null
  },
  {
    "id": 3,
    "kind": "lint-warning",
    "phase": "01",
    "file": "src/hermes_arg_connector/service.py",
    "line": 126,
    "description": "Plan-level ruff includes pre-existing unused noqa warning outside this plan's implementation.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T13:30:55.082Z",
    "resolved_at": null
  },
  {
    "id": 4,
    "kind": "unrun-verify",
    "phase": "01",
    "file": ".planning/phases/01-evidence-and-situation-foundation/01-PLAN.md",
    "line": null,
    "description": "Human UI verification requiring a running local API/web fixture was not run in this non-interactive execution.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T13:30:55.145Z",
    "resolved_at": null
  },
  {
    "id": 5,
    "kind": "unrun-verify",
    "phase": "01",
    "file": ".planning/phases/01-evidence-and-situation-foundation/01-03-PLAN.md",
    "line": null,
    "description": "Authenticated local collection returned a successful empty envelope, so no durable detail or audit ID was available for endpoint smoke calls.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T14:35:31.433Z",
    "resolved_at": null
  },
  {
    "id": 6,
    "kind": "unrun-verify",
    "phase": "01",
    "file": "web/src/app/situations/page.tsx",
    "line": null,
    "description": "Desktop, tablet, and mobile visual walkthrough was not performed; automated queue/detail tests cover state transitions and keyboard reachability only.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T14:35:31.497Z",
    "resolved_at": null
  },
  {
    "id": 7,
    "kind": "deviation",
    "phase": "01",
    "file": "scripts/start-api.sh",
    "line": null,
    "description": "Documented uv sync --extra test omitted the API extra; local smoke required the existing locked --extra api to restore uvicorn without dependency changes.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T14:35:31.560Z",
    "resolved_at": null
  },
  {
    "id": 8,
    "kind": "stub",
    "phase": "06",
    "file": "web/src/app/software-inventory/page.tsx",
    "line": 82,
    "description": "Installed Software tab is an intentional tracer placeholder until the ConfigurationData slice is connected in later Phase 6 plans.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T15:23:57.293Z",
    "resolved_at": "2026-08-25T15:43:01.297Z"
  },
  {
    "id": 9,
    "kind": "unrun-verify",
    "phase": "06",
    "file": "web/src/app/software-inventory/page.tsx",
    "line": null,
    "description": "Manual browser walkthrough of /software-inventory was not run; automated page tests cover grouped rows, source warning, review flag, and drill-down.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T15:24:07.515Z",
    "resolved_at": null
  },
  {
    "id": 10,
    "kind": "unrun-verify",
    "phase": "06",
    "file": "web/src/app/software-inventory/page.tsx",
    "line": null,
    "description": "End-of-phase human walkthrough still required: search exact software/version and inspect linked/unlinked environment-bearing details.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T15:42:50.255Z",
    "resolved_at": null
  },
  {
    "id": 11,
    "kind": "unrun-verify",
    "phase": "06",
    "file": "web/src/app/software-inventory/page.tsx",
    "line": null,
    "description": "Human browser walkthrough of healthy and failed workspace refresh was not run in this non-interactive execution.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T15:59:08.032Z",
    "resolved_at": null
  },
  {
    "id": 12,
    "kind": "unrun-verify",
    "phase": "06",
    "file": "web/src/app/software-inventory/page.tsx",
    "line": null,
    "description": "Authenticated browser walkthrough of unknown-OS lifecycle review, candidate inspection, explicit confirmation, refresh persistence, and stale-revision conflict was not run in this non-interactive executor.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T16:14:01.600Z",
    "resolved_at": null
  },
  {
    "id": 13,
    "kind": "deviation",
    "phase": "06",
    "file": "src/intelligence/inventory/eol_review.py",
    "line": null,
    "description": "External web/LLM lifecycle provider remains explicitly unavailable until approved endpoint configuration is supplied.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T16:25:30.658Z",
    "resolved_at": null
  },
  {
    "id": 14,
    "kind": "unrun-verify",
    "phase": "07",
    "file": ".planning/phases/07-unified-resource-inventory/07-06-PLAN.md",
    "line": null,
    "description": "Authenticated browser UX Phase 7 exit walkthrough remains human verification. Live Fabric publication was partially verified by run 0bc31dd4-7965-4650-91f0-b6347c635400: ARG-backed inventory tables wrote to OneLake; LAW software inventory is tracked separately in window #18.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-26T07:16:57.507Z",
    "resolved_at": null
  },
  {
    "id": 15,
    "kind": "deviation",
    "phase": "07",
    "file": "tests/test_onelake_fs.py",
    "line": 257,
    "description": "Full-suite run has pre-existing OneLake filesystem type assertion failure unrelated to inventory read-port changes.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-26T07:16:57.570Z",
    "resolved_at": null
  },
  {
    "id": 16,
    "kind": "deviation",
    "phase": "07",
    "file": "tests/test_situations_ontology.py",
    "line": 25,
    "description": "Full-suite run has pre-existing situation ontology relationship assertion failure outside inventory scope.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-26T07:16:57.635Z",
    "resolved_at": null
  },
  {
    "id": 17,
    "kind": "deviation",
    "phase": "07",
    "file": "tests/test_storage.py",
    "line": 105,
    "description": "Full-suite run has pre-existing partial-publish changedDatasets expectation failure from DatasetStore behavior outside 07-06 scope.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-26T07:16:57.699Z",
    "resolved_at": null
  },
  {
    "id": 18,
    "kind": "live-source-data",
    "phase": "07",
    "file": "src/hermes_arg_connector/logs.py",
    "line": 13,
    "description": "Live LAW software inventory publication authenticated successfully after switching the token audience to https://api.loganalytics.io/.default, but workspace 4cf2b41b-bace-4dd6-8ec0-61c7050ed552 returned SEM0100 because the ConfigurationData table does not exist; inventory_software_observations published 0 rows and source status is degraded.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-26T07:39:43.000Z",
    "resolved_at": null
  },
  {
    "id": 19,
    "kind": "deviation",
    "phase": "07",
    "file": "src/hermes_arg_connector/cli.py",
    "line": null,
    "description": "Verified via Fabric REST API that all 5 inventory_* Delta tables (inventory_os_observations, inventory_resource_observations, inventory_source_status, inventory_software_source_status, inventory_software_observations) are registered in lakehouse operational_context_graph \u2014 data delivery is confirmed. However, publication runs only as an ad hoc inventory-refresh CLI invocation; no native Fabric Data Pipeline/Data Factory artifact or scheduled trigger exists, so nothing appears under the workspace's \"Data pipeline\" item and there is no automated recurring refresh.",
    "status": "open",
    "reason": "Start or attach an active Fabric capacity, then rerun the on-demand job and verify completion.",
    "recorded_at": "2026-08-26T17:25:03.390Z",
    "resolved_at": null
  }
]
````
