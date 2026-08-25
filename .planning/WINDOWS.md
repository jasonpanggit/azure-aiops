---
schema_version: 1
open_count: 9
waived_count: 0
fixed_count: 1
total_count: 10
last_updated: 2026-08-25T15:43:01.297Z
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
  }
]
````
