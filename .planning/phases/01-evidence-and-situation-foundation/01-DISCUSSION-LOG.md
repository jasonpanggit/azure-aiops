# Phase 1: Evidence and Situation Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-24
**Phase:** 1-Evidence and Situation Foundation
**Areas discussed:** Situation model, Evidence normalization, Authorization boundaries, Freshness/quality semantics, Audit persistence

---

## Situation model

| Option | Description | Selected |
|--------|-------------|----------|
| A | Ephemeral correlation only with no durable lifecycle record | |
| B | Durable situation record with lifecycle, severity, priority, scope, owner, and affected resources | ✓ |
| C | External-only incident record with partial local projection | |

**User's choice:** Auto-mode selected durable local situation record model.
**Notes:** Aligns with Phase 1 success criteria for trustworthy, inspectable, auditable situations.

---

## Evidence normalization

| Option | Description | Selected |
|--------|-------------|----------|
| A | Store source-native payloads only | |
| B | Normalize representative source families into common evidence envelope + source metadata | ✓ |
| C | Build source-specific models only and correlate in UI | |

**User's choice:** Auto-mode selected normalized envelope + source metadata.
**Notes:** Preserves source IDs, timestamps, watermarks, and ingestion status required by DETECT-01/02.

---

## Authorization boundaries

| Option | Description | Selected |
|--------|-------------|----------|
| A | UI-only filtering after broad backend access | |
| B | Server-side scope enforcement using Entra claims/RBAC at read boundaries | ✓ |
| C | Deferred authorization hardening to later phase | |

**User's choice:** Auto-mode selected server-side boundary enforcement.
**Notes:** Required to satisfy FOUND-05 and avoid out-of-scope exposure.

---

## Freshness and quality visibility

| Option | Description | Selected |
|--------|-------------|----------|
| A | Hide stale/degraded state and show best-effort aggregates | |
| B | Show explicit freshness, provenance, and quality indicators with stale/contradictory visibility | ✓ |
| C | Surface only binary healthy/unhealthy signal | |

**User's choice:** Auto-mode selected explicit quality/freshness transparency.
**Notes:** Supports operator trust and safe downstream decision quality.

---

## Audit persistence

| Option | Description | Selected |
|--------|-------------|----------|
| A | Mutable event trail in operational tables | |
| B | Append-only immutable audit events for observations and lifecycle actions | ✓ |
| C | Log-only telemetry without durable event model | |

**User's choice:** Auto-mode selected append-only immutable audit events.
**Notes:** Matches FOUND-04 and supports replay/audit use cases in later phases.

---

## the agent's Discretion

- Internal schema naming and index choices remain flexible for planning.
- Exact connector batching and partitioning strategies deferred to phase planning.

## Deferred Ideas

- Recommendation ranking and approval state machine design (Phase 2).
- Typed action execution/verification lifecycle (Phase 3).
- Expanded domain workflows and replay UX breadth (Phase 4/5).
