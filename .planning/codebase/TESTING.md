# Testing Patterns

**Analysis Date:** 2026-09-01

## Test Framework

**Runner:**
- `pytest` (`>=9.0.3,<10`), config in `pyproject.toml` under `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`, `addopts = "-q"` (quiet output by default)

**Assertion Library:**
- Plain `assert` statements (pytest's rewritten asserts) — no separate assertion library
- `pytest.raises(ValueError, match="...")` for exception-path assertions

**Run Commands:**
```bash
pytest                       # Run all tests (225 test files, ~39K lines)
pytest tests/test_incident_agent.py   # Run a single module
pytest -k "incident"          # Run tests matching a keyword
pytest -q                     # Default addopts (quiet)
```
As of the last recorded status in `.planning/STATE.md`: 1583/1587 passing (4 known pre-existing failures in unrelated areas).

## Test File Organization

**Location:** Flat `tests/` directory (not co-located with `src/`), 225 files. No subdirectory nesting by domain — all `test_*.py` files live directly under `tests/`.

**Naming:** `test_<subject>.py`, one file per feature/subsystem, often split further by concern for the same subsystem, e.g.:
- `test_incident_agent.py`, `test_incident_analysis.py`, `test_incident_correlation.py`, `test_incident_patterns.py`, `test_incident_reporting.py`, `test_incident_semantic_integration.py`, `test_incident_v2_hardening.py`, `test_incident_v2_requirements.py`

This "hardening" / "requirements" file-splitting pattern repeats across subsystems (change, patch, predictive, remediation, semantic, lifecycle, operational_context_graph) — new test coverage for a subsystem should follow the same split: base behavior in `test_<subject>.py`, edge cases in `test_<subject>_hardening.py`, contract/requirement checks in `test_<subject>_v2_requirements.py`.

**Fixtures directory:** `tests/fixtures/` holds static JSON/JSONL test data:
- `sample_incident_causality.json`, `sample_change_intelligence.json`, `sample_lifecycle_dataset.json`, `sample_ontology_entities.jsonl`, `mock_inventory_arg.json`, `mcp_protocol.json`, etc.
- `tests/fixtures/inventory_golden/` — golden-file style expected outputs

**Scenario builder modules:** Reusable, non-`test_`-prefixed helper modules at the top of `tests/` construct fully-wired engine instances for reuse across many test files:
- `tests/incident_scenario.py` → `incident_engine()`
- `tests/semantic_scenario.py` → `semantic_scenario()`
- `tests/network_scenario.py`, `tests/change_scenario.py`, `tests/patch_scenario.py`, `tests/remediation_scenario.py`, `tests/predictive_scenario.py`, `tests/lifecycle_scenario.py`, `tests/ontology_comparison_scenario.py`, `tests/topology_comparison_scenario.py`
- `tests/foundry_test_fixtures.py` — shared Foundry-agent-specific fixtures, imported via `from tests.foundry_test_fixtures import ...` (absolute import, requires repo root on `sys.path`)

## Test Structure

**Suite Organization:** Plain functions (`def test_...():`), not class-based `TestCase` suites. Descriptive, sentence-like test names encode the behavior under test:
```python
def test_incident_commands_are_bounded_read_only_and_advisory():
    ...

def test_incident_agent_redacts_identifiers_embedded_in_values():
    ...
```

**Setup pattern:** Construct real domain objects from scenario builders rather than heavy mocking — engines are built with `EngineClass.from_rows(**scenario())` or `EngineClass.from_snapshot(**fixture_dict, now=lambda: fixed_datetime)`. Time is injected via a `now=` callable to keep tests deterministic:
```python
engine = IncidentIntelligence.from_snapshot(
    **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
)
```

**Assertion pattern:** Assert on the full structured dict result and on the JSON-serialized string, particularly to catch security/redaction regressions:
```python
serialized = json.dumps(result)
assert result["read_only"] is True
assert all(item["advisory_only"] for item in result["recommendations"])
assert "/subscriptions/" not in serialized.casefold()
```

## Mocking

**Framework:** `pytest`'s built-in `monkeypatch` fixture is the dominant mocking mechanism — no heavy use of `unittest.mock.patch` decorators observed as primary style.

**Patterns** (`tests/test_api_copilot.py`):
```python
def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(module.FoundryPromptAgent, "_post_once", fake_post_once)
    ...

def test_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("FOUNDRY_AGENT_NAME", raising=False)
```
- Env-var-driven config (`from_env()` constructors) is tested by `monkeypatch.setenv`/`delenv`, not by mocking `os.environ` directly
- Circuit breaker / retry logic is tested by monkeypatching the low-level HTTP call (`_post_once`) to inject controlled failure sequences, then asserting on retry counts, exception types, and timing-based circuit reset behavior

**What to mock:** External HTTP boundaries (`_post_once` for Foundry calls), environment variables, and wall-clock time (`now=` injection) — anything nondeterministic or network-bound.

**What NOT to mock:** Internal domain logic (`SemanticEngine`, `IncidentIntelligence`, `OperationsAgent`) — these are constructed as real objects from fixture/scenario data and exercised directly, favoring integration-style tests over isolated unit mocks of internal collaborators.

## Fixtures and Factories

**Test Data:** Static JSON/JSONL fixtures in `tests/fixtures/` loaded via `Path(...).read_text()` + `json.loads(...)`:
```python
scenario = json.loads(Path("tests/fixtures/sample_incident_causality.json").read_text())
scenario["alerts"][0]["alert_id"] = "/subscriptions/SECRET/..."   # mutate fixture inline for edge cases
engine = IncidentIntelligence.from_snapshot(**scenario, now=lambda: ...)
```
Fixtures are frequently mutated in-place within a test to construct an adversarial/edge-case variant rather than maintaining a separate fixture file per case.

**pytest fixtures:** `@pytest.fixture` decorators used for FastAPI test client/app setup (`tests/test_api_compliance_router.py`, `tests/test_api_copilot.py`) — standard pytest DI for API-layer tests.

**Location:** Static fixtures: `tests/fixtures/`. Scenario builder functions: top-level `tests/*_scenario.py` modules, imported directly by short module name (not through a package), since `tests/` itself is on `sys.path`.

## Coverage

**Requirements:** No coverage threshold enforced in `pyproject.toml`/CI config found; no `pytest-cov` dependency declared. Coverage is tracked informally via pass/fail counts recorded in `.planning/STATE.md` (e.g. "Full suite: 1583/1587 ✅").

## Test Types

**Unit Tests:** Majority of the suite — one module/subsystem per file, testing intelligence engines, agents, and API routers against real in-memory objects built from fixtures.

**Integration Tests:** Cross-cutting `*_semantic_integration.py` files (e.g. `test_change_semantic_integration.py`, `test_incident_semantic_integration.py`, `test_predictive_semantic_integration.py`) verify a specialist agent correctly composes with `SemanticEngine`.

**Contract Tests:** `test_foundry_tool_registry_matches_implementation.py`, `test_mcp_snapshot_contract.py`, `test_inventory_resource_contract.py`, `test_inventory_fabric_contract.py` — assert that declared tool/schema registries match actual runtime implementations, guarding against drift between config and code.

**Hardening/Requirements Tests:** `*_v2_hardening.py` and `*_v2_requirements.py` pairs across many subsystems — hardening files probe edge cases and failure modes; requirements files assert on documented behavioral contracts.

**E2E Tests:** Not present as an automated pytest suite; end-to-end verification is done manually against live Azure/Foundry deployments and recorded narratively in `.planning/STATE.md` (e.g. "all 8 specialists confirmed HTTP 200 via the Responses API").

## Common Patterns

**Async Testing:** `src/operations/foundry_agent.py` uses `asyncio` internally; tests exercise it via monkeypatched sync boundaries (`_post_once`) rather than `pytest-asyncio` fixtures — no `pytest-asyncio` dependency declared, so async code paths are tested by mocking the underlying blocking call, not by awaiting directly in test functions.

**Error/Exception Testing:**
```python
with pytest.raises(ValueError, match="pre-authorized enterprise incident portfolio"):
    operations.analyze("Analyze Incident Causality", "INC-100", subject_type="Incident")
```
Match strings assert on specific, meaningful substrings of the error message rather than just the exception type, keeping tests resilient to message rewording while still validating intent.

**Security-regression pattern:** Repeatedly assert that serialized output never leaks ARM resource IDs, subscription GUIDs, or tenant IDs — even when adversarially embedded/encoded in fixture data (double-URL-encoded ARM IDs, GUIDs embedded in free-text titles). New agent/specialist tests should include an equivalent redaction assertion.

---

*Testing analysis: 2026-09-01*
