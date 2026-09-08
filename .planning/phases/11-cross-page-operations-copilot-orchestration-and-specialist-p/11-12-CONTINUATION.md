---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 12
artifact: continuation
status: blocked
blocked_task: 3
blocked_by: standing release freeze (live operation)
autonomous_tasks_complete: [1, 2]
created: "2026-09-08T12:29:53Z"
---

# Plan 11-12 Continuation — Task 3 held under release freeze

This is a **resumable handoff**, not a SUMMARY. Plan 11-12 is **not complete** and
Phase 11 is **not** complete. `11-12-SUMMARY.md` must NOT be written until Task 3
records a real deployed baseline (or a real recorded HOLD from a real run).

## Completed locally (no live operations)

| Task | Status | Commits |
|---|---|---|
| Task 1 — externalized evaluation corpus + deterministic release gates | ✅ complete | `3d3154fa6` (test RED), `223f9b1bf` (feat GREEN) |
| Task 2 — shadow/canary/promotion/rollback controls | ✅ complete | `da1155e75` (test RED), `b141ef577` (feat GREEN) |
| Task 3 — deploy, evaluate, record real promotion baseline | ⛔ HELD | none — no live op performed |

Local verifications (all green, no live calls):

- `.venv/bin/python -m pytest tests/test_copilot_evaluation_v2.py tests/test_copilot_evaluation.py tests/test_context_evaluation_metrics.py -q` → 74 passed
- `cd infra/terraform && terraform validate -no-color` → valid (init used `-backend=false`; no state touched)
- `bash -n infra/scripts/validate-runtime-e2e.sh` → syntax OK
- `.venv/bin/python scripts/validate_specialist_parity.py --offline` → status pass (8/8 checks incl. `rollout_controls`)
- `ruff check` on changed Python → clean

## Why Task 3 is held (not a precondition failure)

Task 3's `<precondition>` (Azure CLI can read the target resources) is **met** —
`az account show` returns an Enabled subscription. The block is the **standing
release freeze**, because Task 3 is intrinsically a live operation:

- deploy an additive Container Apps revision (`terraform apply` / image build+push),
- run **live** exact specialist/tool/page-mapping parity over the network
  (`validate_specialist_parity.py --live` reaching Foundry + Operations MCP + Azure MCP),
- exercise compatibility → shadow → **bounded canary** traffic on the deployed API,
- run the full 96-case corpus against one deployed build/provider config (real
  model calls and spend), and
- write `.planning/eval/copilot-orchestration-baseline.json` from that deployed run.

All of the above are forbidden under the freeze (no deploy, no image build/push, no
push/merge, no `terraform apply`, no live API calls, no promote/canary).

### No existing durable evidence satisfies the baseline

Checked read-only:

- `.planning/eval/copilot-orchestration-baseline.json` — **absent**.
- `.planning/eval/baseline.json` (2026-08-30, 10 results) and
  `.planning/eval/gold-grounding-baseline.json` (2026-09-02, 23 results, MAF runtime)
  have **no** `dataset_version` / `thresholds_version` / `decision` / `revision`
  fields, predate the Phase-11 corpus, and contain **none** of the four new
  specialists (`inventory_data_health`, `identity_access`, `finops`,
  `resource_health_observability`). They are retained Phase-10 evidence, not a
  Phase-11 canonical-revision promotion baseline. Do **not** rename or repurpose
  them as the baseline — that would be fabricated provenance.

## Exact resume procedure (run only after the freeze lifts)

Follow `docs/runbooks/copilot-orchestration-rollout.md`. In order:

1. **Create** — additive revision deploy (retain the previous revision for rollback):
   `terraform apply -var 'copilot_rollout_mode=compatibility'`.
2. **Validate** — offline then live parity (live is read-only; a `blocked` gate holds, never passes):
   `.venv/bin/python scripts/validate_specialist_parity.py --offline`
   `bash infra/scripts/validate-runtime-e2e.sh`  (with `COPILOT_ROLLOUT_MODE` set per stage)
3. **Switch/Observe** — `shadow`, then bounded `canary`
   (`-var 'copilot_rollout_mode=canary' -var 'copilot_canary_percentage=10'`); shadow must
   not double-run tools/models or expose mutation.
4. **Evaluate** — run the full corpus against the one deployed build/provider config:
   `.venv/bin/python scripts/evaluate_agents.py --dataset tests/fixtures/copilot_evaluation_cases.v1.json --thresholds tests/fixtures/copilot_release_thresholds.v1.json --out .planning/eval/copilot-orchestration-baseline.json`
   (extend the runner to emit the artifact schema below; scoring uses
   `aggregate_release_metrics` + `evaluate_gates`, already implemented and unit-tested).
5. **Record** — the committed artifact must include: `revision`,
   `dataset_version`, `thresholds_version`, manifest/contract versions, provider
   availability, every independent metric, each absolute-threshold gate decision,
   and the overall `PROMOTE` / `HOLD` / affected-mode-disabled outcome. A model
   threshold miss must be recorded as a real **HOLD**, never a fabricated pass.
6. **Verify** — the plan's Task 3 gate (offline, no live calls):
   `.venv/bin/python scripts/evaluate_agents.py --validate-artifact .planning/eval/copilot-orchestration-baseline.json --dataset tests/fixtures/copilot_evaluation_cases.v1.json --thresholds tests/fixtures/copilot_release_thresholds.v1.json`
   Today this prints `{"status":"missing", ...}` and exits 2 (artifact absent) — correct while held.
7. Then complete the end-of-phase UAT `<human-check>` and write `11-12-SUMMARY.md`;
   advance STATE/ROADMAP; only then is the plan complete.

## Release action needed to unblock

A human must **lift the standing release freeze** (or grant a scoped exception for a
Phase‑11 additive canary deploy). Until then, Task 3 stays held. Preserve the Phase‑10
baseline unchanged and retain both the previous revision and the legacy planners for
rollback throughout.
