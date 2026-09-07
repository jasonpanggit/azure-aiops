# Phase 03.1 Deferred Items

## 2026-09-05 — Plan 03.1-05

- `uv run ruff check .` reports 27 pre-existing findings in unrelated infrastructure
  and maintenance scripts, including `infra/scripts/generate_digital_twin_builder.py`,
  `infra/scripts/push_digital_twin_builder.py`,
  `infra/scripts/push_inventory_refresh_pipeline.py`,
  `scripts/delete-lakehouse-tables.py`,
  `scripts/deploy-relationship-suggestion-agent.py`, and
  `scripts/validate-lakehouse-tables.py`. All Plan 03.1-05 changed Python files pass
  Ruff; the unrelated findings were not modified.

## 2026-09-07 — Plan 03.1-25

- The requested broad snapshot/Exposure/remediation/network regression selection
  passed all tests except the pre-existing
  `tests/test_graph_network_traversal.py::test_private_endpoint_exposure_path_reaches_the_backing_resource`.
  `OntologyQueryService` rejects that fixture during graph validation before the
  traversal assertion. Plan 03.1-25 changes only web detail routes, query
  continuity, shared web types/services, and tests; no ontology, network, backend,
  or deployment file was modified, so the unrelated failure was not changed.

## 2026-09-07 — Plan 03.1-19

- The full backend suite retained the previously recorded
  `tests/test_graph_network_traversal.py::test_private_endpoint_exposure_path_reaches_the_backing_resource`
  failure and also reported two failures in
  `tests/test_operational_context_graph_v2_hardening.py`:
  `test_retired_relationship_with_reclassified_endpoint_type_passes_validation`
  and `test_synchronize_resolves_deferred_edge_once_target_entity_appears`.
  All three stop at ontology graph validation. Plan 03.1-19 did not modify
  `src/ontology/graph_queries.py`, `src/ontology/ontology_sync.py`, or either
  failing test file; focused Phase 11, Phase 12, Phase 13, remediation, Plan 19,
  Terraform, and web suites passed.
