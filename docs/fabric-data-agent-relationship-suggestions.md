# Fabric Data Agent — advisory relationship suggestions

This documents the "relationship suggestion" layer requested as an addition
on top of the verified deterministic ontology pipeline
(`src/fabric_pipelines/ontology_pipeline.py`,
committed in `f74335c`). It is **advisory and human-in-the-loop only** — it
never writes into the authoritative `ontology_relationships` Delta table
that the deterministic pipeline owns.

## What this is

A Fabric **Data Agent** item pointed at the `operational_context_graph`
lakehouse's `ontology_entities`/`ontology_relationships` tables, instructed
(via its AI instructions) to look for co-tagging, naming-similarity, or
deployment-correlation patterns and propose *candidate* relationships the
deterministic pipeline didn't derive. Any output it produces is meant to
land in a **separate** staging table, `relationship_suggestions`
(`subject`, `predicate`, `object`, `confidence`, `rationale`,
`status = "pending_review"` by default) — never merged automatically.

## What's real / verified live (this session)

All of the following were exercised against the actual Fabric workspace
`aiops-dev-ops` (`1c328da7-2490-48dc-9ba6-de8c1f333756`), not just written
and assumed correct:

1. **DataAgent item creation** — `POST /workspaces/{id}/items` with
   `type: "DataAgent"` and a definition-parts payload (`data_agent.json`,
   `stage_config.json` with AI instructions, `datasource.json` pointing at
   the lakehouse with `ontology_entities`/`ontology_relationships` selected
   as `lakehouse_tables.table` elements) — **succeeded**, creating item
   `id=3b346ed2-1ed2-4f41-8e9c-bfa152855a8b`, `displayName=relationship_suggestion_agent`.
2. **DataAgent-specific publish** — the generic Items API's
   `.../items/{id}/publish` 404s for DataAgent items; the correct,
   DataAgent-specific path (confirmed by fetching Microsoft Learn's
   "Publish Data Agent" operation page) is
   `POST /workspaces/{id}/dataAgents/{dataAgentId}/staging/publish`, and it
   additionally requires a JSON body of at least `{}` (an omitted body
   400s). Both fixes are implemented in `DataAgentManager.publish()`.
   **Publish succeeded live** (`200 OK`, `{"publishedDescription": null}`).
3. **MCP runtime endpoint reachability** — the published agent's MCP
   endpoint (`https://api.fabric.microsoft.com/v1/mcp/workspaces/{ws}/dataagents/{id}/agent`)
   responds to plain `httpx` JSON-RPC POSTs (no SDK needed — this bypasses
   the namespace-collision blocker described below): `initialize` and
   `tools/list` both returned real, well-formed MCP responses, including a
   discovered tool `DataAgent_relationship_suggestion_agent` with an
   `inputSchema` of `{"userQuestion": string}`.
4. **Definition round-trip verified** — `getDefinition` on the live item
   confirms the staged datasource correctly lists both tables with
   `is_selected: true`, in both the draft and published parts.

## What's NOT working / the actual gap

Calling `tools/call` on the published agent (e.g.
`{"userQuestion": "How many rows are in ontology_entities?"}`) consistently
returns:

```json
{"result": {"content": [{"type": "text", "text": "The Data Agent run failed before producing a result."}], "isError": true}, "id": ..., "jsonrpc": "2.0"}
```

This was retried after fixing the datasource's `elements` selection (which
was initially empty — a real bug this session found and fixed) and after
waiting for propagation, with no change. Both `ontology_entities` and
`ontology_relationships` genuinely exist as Delta tables in the lakehouse
(confirmed via the Lakehouse Tables API, paginating through all 294 tables).
The failure is opaque from the client side — the MCP response gives no
further diagnostic detail (no stack trace or error code), and there is no
equivalent diagnostic log endpoint for Data Agent runs exposed via
this REST surface. This is the honest, currently-undiagnosable gap: the
item is fully and correctly provisioned and published, but the query
execution itself fails server-side for a reason not observable from the
API. Likely candidates (not verifiable without portal/support access):
first-run indexing/warm-up delay beyond what was waited here, a workspace
capacity/SKU limitation on Data Agent query execution, or a preview-feature
platform issue independent of this integration's configuration.

## The original SDK/namespace-collision finding (secondary path, not used)

This repo's `src/fabric/` package is a regular (non-namespace) package
with its own `__init__.py`. The official `fabric-data-agent-sdk` also
publishes under top-level `fabric.dataagent`. Because this repo's editable
install puts `src/` on `sys.path`, `import fabric` always resolves to the
repo's own package first, so `fabric.dataagent` is permanently unreachable
from this repo's own code regardless of the SDK being genuinely installed
(verified: `pip show -f fabric-data-agent-sdk` confirms the files exist in
site-packages; `from fabric.dataagent.client import create_data_agent`
still raises `ModuleNotFoundError`). This is why `DataAgentManager` talks
to the raw Fabric Items/DataAgent REST API directly (mirroring the other
Fabric item managers) instead of using the SDK. In practice this doesn't
matter for provisioning (which works via REST either way), and the plain
`httpx` MCP calls above show the SDK isn't even required for querying —
so this collision, while real, turned out not to be the actual blocker.

## How a human completes the loop today

1. Run `scripts/deploy-relationship-suggestion-agent.py --publish` (safe
   to rerun — idempotently resolves the existing item by name and
   re-stages+republishes its definition).
2. Open the Fabric portal, navigate to the `relationship_suggestion_agent`
   Data Agent item in the `aiops-dev-ops` workspace, and use its chat UI
   to ask it to analyze `ontology_entities`/`ontology_relationships` per
   the instructions in `RELATIONSHIP_SUGGESTION_INSTRUCTIONS`
   (`src/fabric/data_agent_manager.py`) — the portal's own execution path
   may succeed where the plain MCP `tools/call` here did not, since it can
   surface interactive diagnostics/retries this REST-only script cannot.
3. Copy the agent's structured (line-delimited-JSON) response and run it
   through `parse_suggestions()` / `suggestions_to_rows()`
   (`src/fabric_pipelines/relationship_suggestion_parser.py`).
4. Write the resulting rows into the `relationship_suggestions` table
   (contract: `src/fabric_pipelines/relationship_suggestions_contract.py`)
   via the existing `DeltaWriter` helper — never into
   `ontology_relationships`.
5. A human reviews `relationship_suggestions` rows (`status =
   "pending_review"`) and sets `status = "accepted"` on the ones they've
   validated. See "Feedback loop" below for how accepted rows flow back
   into the deterministic pipeline — they are never auto-merged, and
   hand-editing `relationship_builder.py`/`ontology_pipeline.py` is no
   longer required to incorporate them.

## Feedback loop: accepted suggestions → deterministic graph

The last piece of this design closes the loop so a human-approved
suggestion becomes part of the graph on the *next* pipeline run, without
hand-editing code — while keeping the pipeline fully deterministic and
re-runnable (idempotent), and without ever silently overwriting a
deterministically-derived edge.

**How it works end to end:**

1. Data Agent suggests a candidate relationship (currently blocked live —
   see the gap above; the portal chat UI is the fallback path today).
2. A human reviews rows in `relationship_suggestions` and flips
   `status` to `"accepted"` for the ones they trust (out of band — e.g. by
   hand-editing the Delta table, or a future review UI; no such UI exists
   yet, this is a manual step today).
3. On the next `ontology_pipeline.run(...)` call, the caller passes the
   accepted rows via the new `approved_suggestion_rows` parameter (e.g.
   read straight from the `relationship_suggestions` Delta table, filtered
   to `status == "accepted"` — the merge function itself also filters
   defensively, so passing unfiltered rows is safe).
4. `merge_approved_relationship_suggestions()`
   (`src/fabric_pipelines/ontology_pipeline.py`) converts each accepted row
   into a full `ontology_relationships`-shaped row via
   `accepted_suggestion_to_relationship_row()`
   (`src/fabric_pipelines/relationship_suggestions_contract.py`), which
   reuses `RelationshipBuilder`'s own `_relationship_id()`/`stable_version`
   content-addressing scheme (imported directly, not reimplemented) so the
   promoted row gets exactly the `resource_id` a deterministic edge for the
   same subject/predicate/object would get. This is what makes the merge
   idempotent: re-running with the same accepted suggestion twice produces
   the identical row both times, not a duplicate.
5. Every promoted row is tagged `source = "data_agent_suggested_approved"`
   (distinct from deterministic rows' own `source` values), so the two
   provenances are never blurred in the authoritative `relationships`
   output.
6. **Deterministic wins on conflict, always.** If an accepted suggestion's
   subject/predicate/object collides with an edge the deterministic
   pipeline already derived (same content-addressed id), the deterministic
   row is kept unchanged and the collision is recorded in
   `RelationshipMergeResult.conflicts` (with the relationship id, both
   sides' identifying info, and `resolution: "deterministic_kept"`) — never
   silently dropped, never silently overwritten.
7. `OntologyPipelineSummary` now reports `approved_suggestions_merged` and
   `approved_suggestions_conflicts` alongside the existing entity/
   relationship counts, so every pipeline run's summary makes the merge
   outcome visible.

**What's real vs. what's still manual:**

| Step | Status |
| --- | --- |
| Promoting an accepted suggestion row into a relationship-shaped row with correct content-addressed id | **Real, unit-tested** (`test_relationship_suggestion_feedback_loop.py`) |
| Idempotency (same accepted suggestion merges to the same row across reruns) | **Real, unit-tested** |
| Deterministic-wins-on-conflict with explicit, non-silent reporting | **Real, unit-tested** |
| `run()` accepting `approved_suggestion_rows` and folding them into published output | **Real, unit-tested**; existing callers unaffected since the parameter defaults to `()` |
| Data Agent actually producing a suggestion to accept | **Not working** (see gap above) |
| Human review UI for setting `status = "accepted"` | **Does not exist** — manual Delta table edit today |
| End-to-end live proof (real agent suggestion → accepted → merged by an API sync) | **Not exercised** — blocked upstream by the Data Agent invocation gap, not by this merge logic |

In short: the feedback loop's pipeline-side half (merge, provenance,
conflict handling, idempotency) is fully built and verified. Its
Data-Agent-side half remains blocked by the same live invocation issue
documented above, so the loop has been proven piece-by-piece, not
end-to-end against a real live suggestion.

## Summary

| Capability | Status |
| --- | --- |
| DataAgent item creation | **Live, verified** |
| DataAgent publish | **Live, verified** (after fixing path + body) |
| Datasource → lakehouse table selection | **Live, verified** (after fixing empty `elements`) |
| MCP endpoint reachability / tool discovery | **Live, verified** |
| Actually invoking the agent to get suggestions | **Not working** — opaque server-side failure, undiagnosable from this REST surface; portal chat UI is the documented fallback |
| Suggestions → `relationship_suggestions` staging table | Scaffolded (contract + parser + writer path exist and are unit-tested) but not exercised against a real agent response, since no real response was obtainable |
| Auto-merge into `ontology_relationships` | **Deliberately not implemented** — by design, human-in-the-loop only |
| Accepted-suggestion → deterministic-shaped relationship row promotion | **Real, unit-tested** (see "Feedback loop" above) |
| `ontology_pipeline.run()` merging approved suggestions with provenance + conflict handling | **Real, unit-tested**; not yet exercised live end-to-end |
