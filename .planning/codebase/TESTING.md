# Testing Patterns

**Analysis Date:** 2026-08-23

## Test Framework

**Runner:**
- Python tests use `pytest>=9.0.3,<10`, configured in `pyproject.toml`.
- Frontend tests use Vitest 2 with scripts in `web/package.json`; no frontend test files outside dependencies are detected.

**Assertion Library:**
- Python tests use plain `assert` statements and `pytest.raises`, `pytest.mark.parametrize`, and fixtures.
- API tests use `fastapi.testclient.TestClient` assertions against JSON response contracts, as in `tests/test_api_semantic.py`.

**Run Commands:**
```bash
uv run pytest                         # Run Python tests (pytest discovers tests/)
uv run pytest tests/test_api_semantic.py
uv run pytest -k "scope"              # Run matching tests
uv run ruff check .
cd web && npm test                    # Run Vitest once
cd web && npm run test:watch          # Watch mode
```

`testpaths = ["tests"]` and `addopts = "-q"` are set in `pyproject.toml`. A coverage configuration/threshold is not detected.

## Test File Organization

**Location:**
- Python tests are centralized under `tests/`, with fixtures under `tests/fixtures/`; they are not generally co-located with `src/`.
- Large behavior areas have dedicated modules, for example `tests/test_change_analysis.py`, `tests/test_patch_analysis.py`, and `tests/test_network_topology.py`.

**Naming:**
- Files use `test_<feature>.py`; hardening and requirement contracts use suffixes such as `_hardening.py` and `_requirements.py`.
- Test names describe the expected behavior and failure mode, e.g. `test_provider_unavailable`-style contracts in `tests/test_api_semantic.py`.

**Structure:**
```
tests/
├── test_<domain>.py
├── test_api_<surface>.py
├── test_<domain>_hardening.py
├── test_<domain>_requirements.py
└── fixtures/*.json
```

## Test Structure

**Suite Organization:**
```python
@pytest.fixture
def client(tmp_path) -> TestClient:
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(...),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: engine,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)

def test_unknown_subject_is_404_not_500(client):
    response = client.get("/api/v1/applications/NoSuchApp", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
```
This pattern is used in `tests/test_api_semantic.py`.

**Patterns:**
- Use fixtures for reusable clients, engines, clocks, and temporary stores; use `tmp_path` for filesystem isolation.
- Build realistic semantic graphs for API composition tests rather than stubbing the entire domain. `_build_engine` and `make_connection` from `tests/test_connection_lineage_integration.py` are reused by `tests/test_api_semantic.py` and `tests/test_api_copilot.py`.
- Assert both status and contract fields, including error codes, evidence, scope, warnings, and redaction behavior.
- Use parameterization for equivalent invalid inputs or route families, as in `tests/test_fabric_sql_endpoint.py` and `tests/test_api_semantic.py`.

## Mocking

**Framework:** Pytest fixtures and `monkeypatch`; lightweight hand-written fakes/stubs are preferred. `unittest.mock` usage is not a dominant detected pattern.

**Patterns:**
```python
@dataclass
class FakeRunner:
    responses: list[CommandResult]

    def __post_init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout: int) -> CommandResult:
        self.commands.append(command)
        return self.responses.pop(0)
```
This injectable boundary fake appears in `tests/test_azure_clients.py`. `StubAgent` in `tests/test_api_copilot.py` records calls and can inject failure.

**What to Mock:**
- Mock external process, HTTP, agent, clock, and persistence boundaries while testing the application logic: `tests/test_azure_clients.py`, `tests/test_api_copilot.py`, and `tests/test_enrichment_cache.py`.
- Use `monkeypatch` for environment/configuration and controlled retry/failure behavior, as in `tests/test_api_copilot.py`.

**What NOT to Mock:**
- Do not replace the semantic graph or ingestion composition when the behavior under test is retrieval, scope filtering, lineage, or evidence. Use the real harness in `tests/test_api_semantic.py` and `tests/test_connection_lineage_integration.py`.
- Do not call live Azure, Fabric, or public vulnerability services in unit tests.

## Fixtures and Factories

**Test Data:**
```python
cache = EnrichmentCache(
    "cache/feed.json",
    store=OneLakeDocumentStore(tmp_path),
    ttl_seconds=60,
    clock=clock,
)
```
Deterministic JSON fixtures live in `tests/fixtures/`, including `mock_arg_responses.json` and domain scenario datasets.

**Location:**
- Shared domain builders are defined in test modules such as `tests/test_connection_lineage_integration.py`.
- Temporary persistence uses pytest's `tmp_path`; avoid shared mutable repository paths.

## Coverage

**Requirements:** No coverage target or enforcement is detected in `pyproject.toml`, CI configuration, or the test scripts inspected.

**View Coverage:**
```bash
uv run pytest --cov=src --cov-report=term-missing
```
This is a usable ad hoc command, but `pytest-cov` is not declared in the project test extras.

## Test Types

**Unit Tests:**
- Deterministic normalization, configuration, caching, validation, scoring, and error translation are tested directly; examples include `tests/test_normalize.py`, `tests/test_config.py`, `tests/test_enrichment_cache.py`, and `tests/test_api_http.py`.

**Integration Tests:**
- API tests build real domain/semantic components and exercise HTTP composition with `TestClient`, while external providers are replaced at their boundary. See `tests/test_api_semantic.py` and `tests/test_connection_lineage_integration.py`.
- Storage and connector integrations use temporary stores and injectable runners, as in `tests/test_azure_clients.py` and `tests/test_storage.py`.

**E2E Tests:**
- A browser E2E suite is not detected. Frontend has Vitest dependencies/scripts in `web/package.json`, but no repository-owned `web/*.test.*` or `web/*.spec.*` files were found.

## Common Patterns

**Async Testing:**
- Async behavior is generally exercised through synchronous service/API wrappers or direct async tests where present; use pytest async support only when the target API is async. Do not introduce event-loop management into ordinary synchronous tests.

**Error Testing:**
```python
def test_arg_client_raises_actionable_error() -> None:
    runner = FakeRunner([CommandResult(1, "", "not logged in")])
    client = AzureCliArgClient(runner=runner)
    with pytest.raises(RuntimeError, match="not logged in"):
        client.query(spec, ["sub-1"])
```
For HTTP surfaces, assert stable `error.code` and status rather than brittle full messages, as in `tests/test_api_semantic.py`.

---

*Testing analysis: 2026-08-23*
