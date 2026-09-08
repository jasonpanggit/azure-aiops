---
created: 2026-09-08T15:53:26.557Z
title: Add activation publication progress logging
area: general
severity: minor
files:
  - src/onboarding/activation.py:169-215
  - src/fabric/sync_service.py:340-822
  - src/onboarding/cli.py:190-260
  - tests/test_fabric_sync_service.py
---

## Problem

Production Exposure activation can take 30-40 minutes while emitting no output
between initial discovery warnings and the terminal result. Operators cannot
distinguish healthy high-cardinality processing from a hung Job, and must query
ACA execution state, Log Analytics, Fabric tables, and the Gold pointer
separately. The current progress callback reports completed Fabric table writes
to in-process callers but the activation CLI does not expose structured
stage-level progress or periodic heartbeats.

The live Plan 03.1-19 run processes roughly 150,000 Defender observations,
builds an approximately 80,000-entity / 233,000-relationship ontology, and
publishes dozens of Delta tables before the final pointer CAS. Logging every row
would be unsafe and noisy, but long silent periods are operationally confusing.

## Solution

Add bounded, structured progress events for the activation/publication lifecycle:

- connection validation and discovery start/completion;
- combined snapshot publication;
- dataset mapping and workload/temporal/container projection;
- granular ontology construction and validation counts;
- Fabric table publication as `completed/total`, with table name, row count, and
  elapsed duration;
- Fabric asset registration, ontology publication, Gold staging, shortcut
  finalization, and pointer activation;
- a low-frequency heartbeat during long stages that includes stage name and
  elapsed time without resource IDs, payloads, secrets, or per-row output;
- terminal failure output containing the sanitized failing stage and elapsed
  time.

Reuse the existing `FabricTableWriteProgress` callback and logging conventions
instead of adding a parallel progress system. Keep metrics low-cardinality and
make heartbeat frequency configurable or clock-injectable for deterministic
tests. Add tests proving ordered stage transitions, bounded heartbeat behavior,
table completion counts, sanitized failures, and no change to pointer
activation ordering.
