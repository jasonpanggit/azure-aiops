---
phase: 09
slug: consumer-pivot
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-28
---

# Phase 09 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest for API; Vitest/ project web test runner for React |
| **Config files** | `pyproject.toml`, `web/package.json` |
| **Quick API command** | `python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py -q` |
| **Quick web command** | `cd web && npm test -- --run src/components/ui/CopilotDrawer.test.tsx src/components/ui/CopilotDrawerButton.test.tsx` |
| **Full commands** | `python -m pytest -q`; `cd web && npm run lint && npm test` |

## Sampling Rate

- After each backend task: run the quick API command.
- After each web task: run the quick web command plus `cd web && npm run lint`.
- After each plan wave: run the relevant API and web suites.
- Before verification: run both full suites and the production web build if available.

## Per-Task Verification Map

| Task ID | Plan | Requirement | Secure behavior | Test type | Automated command | Status |
|---------|------|-------------|-----------------|-----------|-------------------|--------|
| 09-01-01 | 09-01 | INV-09, INV-10 | Typed snapshot rejects invalid version, oversized/unscoped data, and malformed citations | unit/API | `python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py -q` | pending |
| 09-01-02 | 09-01 | INV-09 | Network checks are deterministic-first and findings retain policy/evidence/uncertainty fields | unit/integration | `python -m pytest tests/test_api_copilot_snapshot.py tests/test_api_copilot_investigation.py tests/test_network_analysis.py -q` | pending |
| 09-02-01 | 09-02 | INV-10 | Identity consumers use the read port; no raw identity dataset reads remain | regression | `python -m pytest tests/test_inventory_read_port.py tests/test_agent_queries.py -q` | pending |
| 09-02-02 | 09-02 | INV-10 | Foundry/Fabric IQ tools are allowlisted, provenance-bearing, bounded, and degrade explicitly | unit/integration | `python -m pytest tests/test_foundry_agent.py tests/test_api_runtime.py tests/test_fabric_client.py -q` | pending |
| 09-03-01 | 09-03 | INV-09, INV-10 | Every supported page submits typed visible state and preserves per-family availability | UI/unit | `cd web && npm test -- --run src/components/ui/CopilotDrawer.test.tsx src/components/ui/CopilotPageIntegrations.test.tsx` | pending |
| 09-03-02 | 09-03 | INV-09 | Drawer exposes loading, partial, fallback, retry, and failure states with accessible semantics | UI/accessibility | `cd web && npm run lint && npm test -- --run src/components/ui/CopilotDrawer.test.tsx` | pending |

## Manual-Only Verifications

| Behavior | Why manual | Test instructions |
|----------|------------|-------------------|
| Named Foundry specialists and Fabric IQ ontology tool are available in the target tenant | Preview/API/permission availability is tenant-specific | Invoke the capability smoke test, verify each configured agent identity/version, confirm IQ query provenance and scope, then disable the dependency and verify deterministic fallback |
| Page-level Copilot is understandable and keyboard/screen-reader usable | Visual and assistive technology behavior cannot be fully inferred from unit tests | Open each supported page, launch with keyboard, inspect focus/escape/live-region behavior, submit a question, and confirm the panel cites the visible snapshot |

## Wave 0 Requirements

- Add or extend API fixtures for valid, stale, partial, denied, unavailable, oversized, and out-of-scope page snapshots.
- Add deterministic Network policy/check fixtures covering NSG, routes, firewall, segmentation, and blast-radius evidence.
- Add Foundry unavailable/invalid-output and Fabric IQ unavailable/unauthorized fixtures.
- Add UI fixtures/assertions for each supported page kind and staged drawer state.

## Validation Sign-Off

- [ ] All plan tasks have automated verification or an explicit manual checkpoint.
- [ ] Snapshot, scope, evidence, fallback, and accessibility behavior are covered.
- [ ] No three consecutive implementation tasks lack automated feedback.
- [ ] `nyquist_compliant: true` set after execution validation.
