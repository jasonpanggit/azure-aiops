# Deferred Items — Phase 10

Out-of-scope discoveries logged during plan execution. Not fixed here per the
executor's scope-boundary rule (only auto-fix issues directly caused by the
current task's changes).

## From 10-02 execution (ownership/tag-coverage rule)

- **`tests/test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state`**
  and **`tests/test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`**
  fail on a full `pytest -q` run. Root cause is unrelated to 10-02's changes
  (`src/fabric/data_quality.py`, `fabric.config.example.yaml`,
  `tests/test_data_quality.py`): both failing tests exercise
  `onboarding.ingestion_service`, and the working tree at execution time
  already had uncommitted, in-progress changes to `src/onboarding/sync.py`,
  `src/api/runtime.py`, and `src/fabric/telemetry.py` (the latter carrying a
  code comment referencing "10-03 threat model T-10-03-01" / MED-01 publish
  preflight work) — i.e. concurrent work-in-progress from another
  plan/session, not something 10-02 touched or introduced.
  Confirmed isolated: `tests/test_data_quality.py`, `tests/test_ontology_validator.py`,
  `tests/test_incremental_sync.py`, and `tests/test_api_vulnerability_router.py`
  (the modules that reference `data_quality`/`DataQualityValidator`) all pass
  green after the 10-02 changes. Re-check once the 10-03-adjacent work lands.
