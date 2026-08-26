# Phase 7 Fabric Pivot

**Date:** 2026-08-26
**Status:** 07-03 replanned; 07-04 through 07-06 pending replan

## Decision

Fabric/OneLake is the unified inventory data platform and durable source of truth.

Inventory remains the owner of acquisition, normalization, retention, source status, and publication lifecycle. Hermes, API, UI, and other subsystems consume inventory through inventory-owned read ports over Fabric-backed data. Hermes must not manage inventory lifecycle, and the long-term pivot must remove duplicate Hermes ARG acquisition for resource identity.

## Impact

- 07-01 characterization remains valid and protects current dataset names, row shapes, and retention semantics.
- 07-02 neutral storage extraction remains valid shared infrastructure and compatibility work.
- The original 07-03 was stale because it assumed the next move was DatasetStore-only ownership inversion.
- 07-03 has been replaced with a Fabric-backed ownership inversion plan covering Fabric table/lakehouse contracts, Fabric sync/quality gates, source status and watermark semantics, and compatibility reads.
- 07-04 through 07-06 remain stale until replanned around the Fabric-backed contract.

## Replan requirements

1. Define the Fabric-backed inventory publication contract before moving more code.
2. Keep the inventory pipeline independent of Hermes; Hermes is only a consumer.
3. Preserve 07-01 observable OS/software contracts until an intentional migration plan changes them.
4. Decide how neutral `DatasetStore` relates to Fabric-backed inventory: staging/compatibility, local fallback, or replaced publication backend.
5. Ensure PaaS and future resource families land in Fabric-backed inventory from the start.
6. Define consumer read ports over Fabric-backed inventory rather than direct `inventory/*` dataset reads.

## Blocked stale work

Do not execute any pre-pivot copy of `07-03-PLAN.md`. The current `07-03-PLAN.md` is the Fabric-backed replacement and is the next executable plan. Replan `07-04-PLAN.md` through `07-06-PLAN.md` before executing them.
