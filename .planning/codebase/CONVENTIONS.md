# Coding Conventions

**Analysis Date:** 2026-09-01

## Naming Patterns

**Files:**
- Python modules use `snake_case.py`: `src/operations/foundry_agent.py`, `src/intelligence/incident/incident_intelligence.py`
- Domain packages grouped by capability under `src/`: `agents/`, `operations/`, `intelligence/`, `semantic/`, `ontology/`, `fabric/`, `network/`, `api/`, `mcp_server/`, `storage/`, `onboarding/`
- Test files mirror the module under test with a `test_` prefix: `tests/test_incident_agent.py` for `src/agents/.../incident`
- Scenario/fixture builder modules use `_scenario.py` suffix (not `test_` prefixed, imported by multiple test files): `tests/incident_scenario.py`, `tests/semantic_scenario.py`, `tests/network_scenario.py`

**Functions:**
- `snake_case`, verb-led: `analyze()`, `from_env()`, `from_snapshot()`, `from_rows()`
- Private/internal helpers prefixed with single underscore: `_post_once`, `_extract_text`, `_MUTATION_WORDS`

**Variables/Constants:**
- Module-level constants are `UPPER_SNAKE_CASE` with descriptive env-var names: `ENV_PROJECT_ENDPOINT`, `DEFAULT_API_VERSION`, `SPECIALIST_IDS`, `DEFAULT_TIMEOUT_SECONDS`
- Env var constants store the literal env var name as the value (`ENV_PROJECT_ENDPOINT = "FOUNDRY_PROJECT_ENDPOINT"`), never read directly via `os.environ[...]` inline — always through the named constant

**Types/Classes:**
- `PascalCase` for classes: `OperationsAgent`, `SemanticEngine`, `IncidentIntelligence`, `FoundryPromptAgent`
- Exception hierarchies use `Error` suffix and inherit from a shared domain base: `FoundryAgentError(RuntimeError)` → `FoundryAgentNotConfigured`, `FoundryCircuitOpenError`, `_RetryableFoundryError`
- Dataclasses used for structured config/value objects (`@dataclass`) rather than plain dicts for internal state

## Code Style

**Formatting/Linting:**
- `ruff` is the sole lint/format tool (`pyproject.toml` `[tool.ruff.lint.per-file-ignores]`), version pinned `>=0.16,<0.17`
- `__init__.py` files are exempted from `N999` (module naming) and `E402` (import order) — package `__init__.py` files may re-export symbols after conditional logic
- `from __future__ import annotations` is used at the top of modules to enable lazy annotation evaluation (seen in both src and test files) — always add this to new modules using modern type hints

**Type Hints:**
- Python 3.11+ required (`requires-python = ">=3.11"`)
- `typing.Any` and `typing.Protocol` used sparingly for loosely-typed integration boundaries (`src/operations/autonomous_investigation.py`, `src/operations/foundry_agent.py`)
- Prefer concrete types elsewhere; `Any` is reserved for external API response shapes

## Import Organization

**Order (standard Python grouping, blank-line separated):**
1. `from __future__ import annotations`
2. Standard library (`json`, `logging`, `os`, `threading`, `time`, `urllib.*`, `pathlib`, `datetime`)
3. Third-party (`pytest`, `httpx`, etc.)
4. First-party/local absolute imports rooted at `src/` (no relative imports observed): `from agents.operations.operations_agent import OperationsAgent`
5. Test-only local scenario helpers imported directly by name: `from incident_scenario import incident_engine`

**Path Resolution:**
- No import path aliases; `src/` is inserted at the front of `sys.path` in `tests/conftest.py` so first-party packages always win over any same-named third-party package (guards against `agents` package collision with the `openai-agents` PyPI distribution)
- Repo root is also added to `sys.path` so `tests.foundry_test_fixtures` absolute imports resolve

## Error Handling

**Patterns:**
- Domain-specific exception hierarchies per subsystem, all deriving from a module-level base error (e.g. `FoundryAgentError(RuntimeError)`), not bare `Exception`
- Validation failures raise descriptive `FoundryAgentError` messages naming the offending agent and field: `raise FoundryAgentError(f"{agent_id} finding id is required")`
- Exception chaining preserved with `raise ... from exc` when converting a lower-level error (`json.JSONDecodeError`, `TypeError`) into a domain error
- Retry/circuit-breaker pattern implemented explicitly for external HTTP calls to Foundry (`_RetryableFoundryError`, `FoundryCircuitOpenError`) rather than relying on a third-party retry library — see `src/operations/foundry_agent.py`
- Read-only/advisory invariants are enforced via assertions inside business logic and tested explicitly (`assert result["read_only"] is True`), not just documented

## Logging

**Framework:** Standard library `logging`, one `_LOGGER = logging.getLogger(__name__)` per module (module-level, private-underscore name)

## Comments & Docstrings

**Module docstrings:** Every significant module opens with a triple-quoted docstring explaining *why* the module exists and its design rationale, not just what it does — see `src/operations/foundry_agent.py` header, which explains the two-stage retrieval/narration split and why the model must never invent inventory data. Follow this pattern for new modules: state the architectural constraint, not just the mechanism.

**Inline comments:** Reserved for non-obvious rationale (e.g. explaining a `sys.path` manipulation workaround in `tests/conftest.py`, or noting Foundry's API is versioned by literal string `"v1"` not a date). Avoid restating code in comments.

## Function Design

**Size:** Functions are kept single-purpose; validation logic in `foundry_agent.py` is composed of many small `raise FoundryAgentError(...)` guard clauses in sequence rather than nested conditionals.

**Parameters:** Public entry points accept an explicit `subject_type` / `agent_id` discriminator to route behavior instead of relying on class hierarchies — e.g. `operations.analyze(command, "Enterprise", subject_type="IncidentPortfolio")`.

**Return Values:** Analysis functions return structured `dict` payloads with a stable contract shape (`subject`, `read_only`, `recommendations`), always JSON-serializable — tests assert directly on `json.dumps(result)` to catch accidental leakage of secrets/IDs.

## Module Design

**Security-by-construction:** Business logic actively redacts/guards against embedding ARM resource IDs, subscription GUIDs, and tenant IDs in string output; this is enforced both in code and in tests (`assert "/subscriptions/" not in serialized.casefold()`). Any new specialist/agent module handling identifiers must implement equivalent redaction and add a corresponding regression test.

**Config via environment:** All external integration config (Foundry endpoint, agent name, timeouts, circuit breaker thresholds) is read through named `ENV_*` constants with `from_env()` classmethod constructors, never scattered `os.environ` calls.

---

*Convention analysis: 2026-09-01*
