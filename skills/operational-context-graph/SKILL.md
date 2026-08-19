---
name: operational-context-graph
description: Use when querying Azure operational ownership or impact.
---

# Operational Context Graph

Use the read-only `operations_analysis` tool for evidence-backed application/service/resource health, ownership, topology, impact, risk, incident context, compliance, summaries, and advisory recommendations.

## Query procedure

1. Select the closest supported value for `command`; never invent a mutation or remediation command.
2. Put the exact semantic entity name in `subject` and set `subject_type` when the command is generic or the name may be ambiguous.
3. Report only graph-backed results returned by the tool.
4. If no entity matches, say so; do not infer an owner, application, service, environment, or team.
5. For stale or missing context, recommend correcting Azure tags/source inventory and having an operator run `hermes-arg fabric "Sync operational ontology"`; agents do not receive mutation/ingestion tools.

## Supported examples

- What does this VM belong to?
  - `command="Analyze VM"`
- What business service owns this?
  - `command="Analyze Business Service"`
- Show dependencies of Application X.
  - `command="Show Impact Summary"`, `subject_type="Application"`
- Which applications are affected by patch failures?
  - `command="Analyze Patch Compliance"`
- Find resources with missing ownership.
  - `command="Find Resources With Missing Ownership"`, `subject="Enterprise"`
- What is impacted if this server fails?
  - `command="Generate Incident Context"`, with the server asset type

Do not initiate remediation, create tags, or mutate Azure/Fabric data from a query.
