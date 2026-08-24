# Testing Patterns

**Analysis Date:** 2026-08-24

## Test Framework

**Runner:**
- Backend tests use `pytest` (declared in `pyproject.toml` and executed in CI via `.github/workflows/ci.yml`).
- Frontend tests use `vitest` with `jsdom`, configured in `web/vitest.config.ts` and invoked through `web/package.json` scripts.

**Assertion Library:**
- Python uses native `assert` plus `pytest.raises`, `pytest.mark.parametrize`, fixtures, and `monkeypatch`, for example in `tests/test_api_semantic.py` and `tests/test_subscription_cli.py`.
- Frontend uses Vitest `expect` and Testing Library assertions (`@testing-library/jest-dom/vitest` in `web/src/test/setup.ts`), for example `web/src/components/DataCard.test.tsx` and `web/src/app/agents/page.test.tsx`.

**Run Commands:**
```bash
python -m pytest                      # CI baseline (see .github/workflows/ci.yml)
python -m ruff check src tests        # CI lint gate
uv run pytest                         # Local Python test run
uv run pytest tests/test_api_semantic.py
cd web && npm test                    # vitest run
cd web && npm run test:watch          # vitest watch
```

`testpaths = ["tests"]` and `addopts = "-q"` are set in `pyproject.toml`.

## Test File Organization

**Location:**
- Python tests are centralized under `tests/`, with fixtures under `tests/fixtures/`.
- Frontend tests are mostly co-located with source files in `web/src/**` using `.test.ts` and `.test.tsx`.

**Naming:**
- Python files: `test_<feature>.py`, with targeted suites such as `_hardening.py` and `_requirements.py` (`tests/test_patch_v2_hardening.py`, `tests/test_predictive_v2_requirements.py`).
- Frontend files: `<module>.test.ts[x]` (`web/src/lib/network-services.test.ts`, `web/src/app/remediation/page.test.tsx`).

**Structure:**
```
tests/
├── test_<domain>.py
├── test_api_<surface>.py
├── test_<domain>_hardening.py
├── test_<domain>_requirements.py
└── fixtures/*.json

web/src/
├── app/**/page.test.tsx
├── components/**/*.test.tsx
└── lib/**/*.test.ts
```

## Test Structure

**Suite Organization:**
```python
@pytest.fixture
def client(tmp_path) -> TestClient:
        engine = _build_engine(make_connection())
        context = ApiContext(..., semantic_provider=lambda: engine)
        return TestClient(create_app(context), raise_server_exceptions=False)

def test_unknown_subject_is_404_not_500(client):
        response = client.get("/api/v1/applications/NoSuchApp", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
```
Pattern source: `tests/test_api_semantic.py`.

```typescript
describe("apiRequest", () => {
    afterEach(() => vi.restoreAllMocks());

    it("throws a typed ApiError for an error contract response", async () => {
        mockFetch({ status: 404, body: { error: { code: "not_found", message: "no such connection", details: {} } } });
        await expect(apiRequest("/subscription-connections/missing", { anonymous: true })).rejects.toMatchObject({
            code: "not_found",
            status: 404,
        });
    });
});
```
Pattern source: `web/src/lib/api-client.test.ts`.

**Patterns:**
- Build reusable fixtures for context setup and dependency injection (`tests/test_api_semantic.py`).
- Favor behavior contracts at API boundaries: assert status, `error.code`, scope, evidence, and key payload fields.
- Use `pytest.mark.parametrize` heavily for invalid-input and boundary matrices (`tests/test_fabric_sql_endpoint.py`, `tests/test_patch_v2_hardening.py`).
- Frontend tests focus on user-visible behavior and state transitions (`web/src/app/agents/page.test.tsx`, `web/src/app/connections/page.test.tsx`).

## Mocking

**Framework:**
- Python: `monkeypatch` and hand-written fakes/stubs.
- Frontend: `vi.mock`, `vi.hoisted`, `vi.fn`, and fetch stubs.

**Patterns:**
```python
def test_cli_local_spn_injects_env_backed_connection(tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")
        assert _run(["local-spn", "--home", str(tmp_path / "hermes-local")]) == 0
```
Source: `tests/test_subscription_cli.py`.

```typescript
const { action, catalog, investigate } = vi.hoisted(() => ({
    action: vi.fn(),
    catalog: vi.fn(),
    investigate: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
    multiAgentApi: { action, catalog, investigate },
}));
```
Source: `web/src/app/agents/page.test.tsx`.

**What to Mock:**
- External boundaries and mutable runtime context: environment variables, network/process adapters, and service clients.
- Frontend service modules and network fetch for deterministic UI tests.

**What NOT to Mock:**
- Avoid mocking away semantic composition when testing semantic API behavior; reuse real harness/builders (`tests/test_connection_lineage_integration.py`, `tests/test_api_semantic.py`).
- Do not hit live cloud services in unit/integration tests.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def client(tmp_path) -> TestClient:
        context = ApiContext(onboarding=SubscriptionOnboardingService(tmp_path / "hermes"), ...)
        return TestClient(create_app(context), raise_server_exceptions=False)
```
Source: `tests/test_api_semantic.py`.

```typescript
const envelope = <T,>(data: T) => ({
    data,
    evidence: [...],
    scope: {},
    knowledge_version: "graph-1",
});
```
Source: `web/src/app/agents/page.test.tsx`.

**Location:**
- JSON fixtures live in `tests/fixtures/` (for example `tests/fixtures/mock_arg_responses.json`).
- Frontend setup bootstraps jest-dom matchers in `web/src/test/setup.ts`.

## Coverage

**Requirements:**
- No explicit coverage threshold or coverage gate is detected in `pyproject.toml`, `web/package.json`, or `.github/workflows/ci.yml`.

**View Coverage:**
```bash
uv run pytest --cov=src --cov-report=term-missing
cd web && npx vitest run --coverage
```
These are ad hoc commands; coverage tooling is not currently wired into CI.

## Test Types

**Unit Tests:**
- Core normalization/config/cache/validation logic is tested directly (`tests/test_normalize.py`, `tests/test_config.py`, `tests/test_enrichment_cache.py`).
- Frontend utility units are tested in `web/src/lib/*.test.ts` (`web/src/lib/scope.test.ts`, `web/src/lib/permissions.test.ts`).

**Integration Tests:**
- API integration uses FastAPI `TestClient` with realistic semantic/domain composition (`tests/test_api_semantic.py`).
- CLI integration validates command behavior and output contracts with patched service dependencies (`tests/test_subscription_cli.py`).
- Frontend page-level integration tests render complete pages and mock service boundaries (`web/src/app/investigate/page.test.tsx`, `web/src/app/remediation/page.test.tsx`).

**E2E Tests:**
- Browser E2E framework (Playwright/Cypress) is not detected in repository-owned test suites; current frontend coverage is component/page integration through Vitest + Testing Library.

## Common Patterns

**Async Testing:**
```typescript
it("runs agents ...", async () => {
    renderPage();
    expect(await screen.findByText("Network Agent")).toBeInTheDocument();
    await waitFor(() => expect(action).toHaveBeenCalledWith("mai-123", "assign_owner", { owner: "Finance Ops" }, {}));
});
```
Source: `web/src/app/agents/page.test.tsx`.

**Error Testing:**
```python
def test_unknown_subject_is_404_not_500(client):
        response = client.get("/api/v1/applications/NoSuchApp", headers=HEADERS)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
```
Source: `tests/test_api_semantic.py`.

HTTP and UI tests consistently assert stable machine-readable error contracts (`error.code`, status) instead of brittle full-text message matching.

---

*Testing analysis: 2026-08-24*
