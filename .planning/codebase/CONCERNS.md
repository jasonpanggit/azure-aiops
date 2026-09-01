# Codebase Concerns

**Analysis Date:** 2026-09-01

## Tech Debt

**MCP dispatcher — unimplemented tool dispatch:**
- Issue: `TODO: Dispatch tool call to azure-mcp-server library with resolved credential` — the standalone MCP server app has a code path that is explicitly not wired up.
- Files: `src/mcp_server/app.py:213`
- Impact: Depending on which code path is live vs. superseded by the ACA-deployed Microsoft Azure MCP Server (per `.planning/STATE.md` Phase 09-11), this may be dead/legacy code, or an unfinished fallback. Needs disambiguation before further work builds on it.
- Fix approach: Confirm whether `src/mcp_server/app.py` is still on the serving path post-09-11 pivot to the official Azure MCP Server in ACA; if legacy, remove or clearly mark deprecated; if live, complete the dispatch implementation.

**Coarse per-process circuit breaker as a stand-in for real throttling:**
- Issue: `MAX_CALLS = 100_000` in the MCP dispatcher is a blunt, per-process lifetime cap (previously a much lower `25` that caused whole-container failure after 25 calls across *all* users — fixed this session per STATE.md).
- Files: `src/operations/mcp_server.py:23`
- Impact: Real throttling now depends entirely on APIM's `rate-limit-by-key`/`quota-by-key` policies; if those policies are ever removed or misconfigured, there is no meaningful in-process protection against runaway tool-calling loops from a single caller.
- Fix approach: Document the split responsibility clearly in code comments (already partially done) and add an integration test asserting APIM rate-limit policies exist and are attached to the MCP surface.

**Widespread repetition of magic serialization/row limits:**
- Issue: `max_serialized_bytes=1_000_000` (and similar `max_resources`, `max_history_rows`, `max_output_items` defaults) is duplicated as a literal default across at least 8 intelligence-engine constructors instead of a shared constant/config object.
- Files: `src/intelligence/predictive/predictive_intelligence.py:57`, `src/intelligence/change/change_intelligence.py:56`, `src/intelligence/lifecycle/lifecycle_intelligence.py:71`, `src/intelligence/patch/patch_intelligence.py:231`, `src/intelligence/incident/incident_intelligence.py:70`, `src/intelligence/remediation/remediation_planner.py:78`, `src/agents/operations/operations_agent.py:96`, `src/semantic/semantic_engine.py:66`
- Impact: Tuning these limits (e.g., raising payload caps for a larger tenant) requires touching 8+ files; easy to miss one and get inconsistent truncation behavior across specialist agents.
- Fix approach: Extract a shared `IntelligenceEngineLimits` dataclass/constants module and have each engine's constructor default to it.

**Large "god files" concentrating too much responsibility:**
- Issue: Several files exceed 1,000–1,900 lines, suggesting they've absorbed multiple responsibilities over time.
- Files: `src/api/runtime.py` (1,929 lines, 10 broad `except Exception` blocks), `src/semantic/semantic_engine.py` (1,885), `src/fabric/sync_service.py` (1,415, 4 broad excepts), `src/operations/autonomous_investigation.py` (1,128, 7 broad excepts), `src/intelligence/patch/patch_intelligence.py` (1,107), `src/fabric/dataset_mapper.py` (1,094), `src/agents/operations/operations_agent.py` (1,033), `src/intelligence/inventory/service.py` (1,015)
- Impact: High cognitive load for onboarding/modification; higher risk of regressions when touching shared state inside these modules; harder to unit test in isolation.
- Fix approach: When next touching these files for feature work, extract cohesive sub-responsibilities (e.g., runtime.py's request-handling vs. lifecycle-management vs. error-formatting) into dedicated modules rather than adding more code inline.

**Confidence-score magic numbers being actively remediated:**
- Issue: A comment in the ontology layer notes "Confidence values used to be hardcoded magic numbers scattered across [call sites]" — implying a partial migration to a central module.
- Files: `src/ontology/confidence.py:3,21`
- Impact: If any call sites were missed during the migration, confidence scoring could be inconsistent between entity types.
- Fix approach: Grep for any remaining bare float confidence literals outside `confidence.py` and migrate them.

## Known Bugs

**Previously fixed but worth regression-testing (per STATE.md history):**
- Symptoms (historical): MCP dispatcher permanently broke every container after 25 total tool calls across all users (lifetime, not per-request cap); APIM `/mcp-server` HTTP 500 from null JWT-claim dereference; MCP tool-error results crashing the Foundry .NET MCP client; empty-string (`""`) optional tool arguments rejected by Pydantic `min_length=1`; `apim_publisher_email` empty string tripping the wrong Terraform validator; `foundry_model_capacity` silently reverted by every `terraform apply`.
- Files: `src/operations/mcp_server.py`, `src/operations/page_context.py` (field validators — `min_length=1` pattern is still present elsewhere and should be checked for the same optional-empty-string trap), APIM policy XML (not in this repo tree directly reviewed), `scripts/deploy.sh` / `.env.local`
- Trigger: All were discovered during live end-to-end testing in the 09-11 phase, not caught by the existing test suite.
- Workaround/status: Fixed as of the last STATE.md update, but the fact these shipped past 1583 passing tests signals a coverage gap around live multi-tool-call agent turns and Terraform env-var plumbing — see Test Coverage Gaps below.

**4 pre-existing test failures (unspecified):**
- Symptoms: STATE.md reports "Full suite: 1583/1587 ✅ (4 pre-existing failures in unrelated areas, last checked pre-session)".
- Files: Unknown — not identified in STATE.md; requires running `pytest -q` (blocked in this sandbox: `python` binary not on PATH) to identify.
- Trigger: Unknown until re-run with correct interpreter (likely `uv run pytest` given `pyproject.toml`/`uv.lock` present).
- Workaround: None documented; treated as accepted/known debt.

## Security Considerations

**Bare/broad exception handling around API and sync boundaries:**
- Risk: 10 broad `except Exception` blocks in `src/api/runtime.py`, 7 in `src/operations/autonomous_investigation.py`, 4 in `src/fabric/sync_service.py` risk silently swallowing security-relevant failures (auth errors, credential resolution failures) and returning generic success/empty responses instead of surfacing them.
- Files: `src/api/runtime.py`, `src/operations/autonomous_investigation.py`, `src/fabric/sync_service.py`
- Current mitigation: Not verified in this pass — would need per-block review to confirm whether errors are re-raised, logged with detail, or truly swallowed.
- Recommendations: Audit each broad except for whether it (a) logs the original exception with stack trace, (b) narrows to expected exception types where feasible, and (c) never converts an auth/credential failure into a "no results" response that could mask an access problem as an empty dataset.

**CORS origins configurable via env var, defaults to localhost:**
- Risk: `AIOPS_API_CORS_ORIGINS` defaults to `http://localhost:3000,http://127.0.0.1:3000` and is otherwise a comma-split list with no allowlist validation against known-good production domains.
- Files: `src/api/app.py:219-224`
- Current mitigation: Requires explicit env var override for non-local origins — safe by default, but if misconfigured with a wildcard or overly broad value in production, `CORSMiddleware` would honor it verbatim.
- Recommendations: Add a startup assertion that rejects `*` in `allow_origins` when running in a non-dev environment, and document required production values alongside `deploy.sh`.

**Multi-subscription managed identity credential model (recent architecture change):**
- Risk: Per `.planning/STATE.md`, the Azure MCP Server now authenticates via a dedicated user-assigned managed identity with per-subscription role assignments (`local.azure_mcp_subscriptions` for-each) rather than the originally-scoped SPN+AKV model. This reduces credential-rotation surface but concentrates a single identity's blast radius across all onboarded subscriptions.
- Files: Terraform config referenced in STATE.md (not directly reviewed in this pass — see `infra/`)
- Current mitigation: Per-subscription role assignments scope what the identity can do in each subscription.
- Recommendations: Verify (via `infra/`) that role assignments are least-privilege per subscription (e.g., `Reader` not `Contributor`) and that the discovery profile is read-only as intended per `BACKLOG.md` HOG-010 ("Azure MCP discovery profile is read-only and namespace-filtered").

**Internet-exposed CIDR detection logic (0.0.0.0/0) — verify completeness:**
- Risk: Network-security gap detection (route tables, NSGs) relies on string-literal matching against `{"internet", "*", "0.0.0.0/0", "any"}` and `"::/0"` for IPv6; any additional equivalent notations (e.g., `0.0.0.0/1` + `128.0.0.0/1` split-default-route tricks, or non-normalized CIDR strings with leading zeros) could bypass detection.
- Files: `src/intelligence/predeploy/simulation.py:211`, `src/network/models.py:449`, `src/network/design.py:122`, `src/network/gaps.py:225,255`, `src/network/addressing.py:52,81`
- Current mitigation: Explicit set-based matching covers the common cases.
- Recommendations: Add test cases for CIDR-splitting evasion patterns and confirm addresses are normalized (case, prefix padding) before comparison.

## Performance Bottlenecks

**Large in-memory serialization caps suggest potential payload-size pressure:**
- Problem: Every intelligence engine independently caps output at ~1MB serialized bytes and bounds `max_resources`/`max_history_rows` in the low thousands — implying these engines have previously hit or approached payload/timeout limits (likely APIM or Foundry response-size limits).
- Files: See "magic serialization/row limits" list above under Tech Debt.
- Cause: Aggregating full tenant history/resource sets in-process before truncation, rather than pushing filtering down to the data source (Fabric/OneLake queries) with server-side limits.
- Improvement path: Where possible, push `max_resources`/`max_history_rows` filtering into the OneLake/Fabric query layer (`src/fabric/`) rather than fetching-then-truncating in Python.

**Large god-files with high cyclomatic complexity risk slow iteration, not necessarily slow runtime:**
- Problem: `src/api/runtime.py` at 1,929 lines is a likely hotspot for request-handling latency debugging given it's both large and exception-heavy.
- Files: `src/api/runtime.py`
- Cause: Concentration of many code paths in one module.
- Improvement path: Once split (see Tech Debt), profile each extracted module independently.

## Fragile Areas

**`src/api/runtime.py` (1,929 lines, 10 broad excepts):**
- Files: `src/api/runtime.py`
- Why fragile: Largest file in the codebase, heaviest use of broad exception handling; any change risks silently altering error-handling behavior for unrelated request paths.
- Safe modification: Add narrow unit tests around the specific handler being changed before modifying; avoid adding new logic inline — extract to a new module and call from `runtime.py`.
- Test coverage: Not verified directly (pytest run blocked by missing `python` binary in sandbox — verify with `uv run pytest tests/ -q`).

**`src/operations/autonomous_investigation.py` (1,128 lines, 7 broad excepts) and `src/operations/foundry_agent.py` (802 lines):**
- Files: `src/operations/autonomous_investigation.py`, `src/operations/foundry_agent.py`
- Why fragile: This is the live MAF-orchestration path (per STATE.md, MAF is now the default Operations Copilot mode) driving all 8 specialist agents through APIM → MCP → Fabric/backend. Bugs here (as evidenced by the string of live-testing fixes in Phase 09-11: JWT null-ref, MAX_CALLS lifetime cap, empty-string validation, tool-error response format) were not caught by the existing 1583-test suite — they only surfaced in live end-to-end smoke testing.
- Safe modification: Any change to tool-calling response parsing (`_extract_text`, `_post_once`/`_post` in `foundry_agent.py`) should be paired with a live smoke test against a real Foundry agent, not just unit tests against mocked response shapes.
- Test coverage: `test_foundry_agent.py` reported 15/15 passing, but this only covers what's mocked; the actual bugs fixed this session were response-shape edge cases the mocks didn't represent.

**Terraform env-var plumbing for deploy-time configuration (`deploy.sh` / `.env.local`):**
- Files: `scripts/deploy.sh`, `web/.env.local` (not committed — config only)
- Why fragile: Two silent-failure incidents this session: an unset `apim_publisher_email` producing a misleading Terraform validator error, and an unwired `AIOPS_FOUNDRY_MODEL_CAPACITY` causing a manual TPM quota bump to be silently reverted by every subsequent `terraform apply`. Both are examples of Terraform variables that have defaults tripping the wrong validation path, or variables not wired from the deploy script at all.
- Safe modification: Before adding any new Terraform variable that has manual/out-of-band operational significance (like quota bumps), audit `deploy.sh` to confirm it's threaded through end-to-end, and add a `terraform plan` diff check to CI/pre-apply flow to catch silent reverts.
- Test coverage: None — these are operational/infra issues not covered by the Python test suite.

## Scaling Limits

**Per-process MCP call cap:**
- Current capacity: 100,000 lifetime tool calls per container process (raised from a bug-level 25).
- Limit: Once a container process reaches 100,000 total calls across all users, it will hard-stop; container recycling (restarts/redeploys) resets the counter.
- Scaling path: Convert to a proper time-windowed or per-caller counter, or remove the process-level counter entirely and rely solely on APIM policies, to avoid an unplanned outage under sustained high traffic.

**APIM rate-limit policy tuned by trial (60→300 calls/60s):**
- Current capacity: 300 calls per 60 seconds (raised this session because 60 was tripped by legitimate multi-tool-call agent turns).
- Limit: Not derived from a capacity model — an empirically-adjusted number that may need re-tuning as more specialist agents or higher-complexity investigation flows are added (8 specialists × N tool calls per turn).
- Scaling path: Model expected tool-calls-per-turn across all 8 specialists and set the policy from that, rather than continuing to bump it reactively when it trips.

## Dependencies at Risk

**Not assessed in this pass** — no `requirements.txt`/`pyproject.toml` dependency audit performed. Recommend a follow-up `pip list --outdated` / `uv pip list --outdated` pass, particularly for the Foundry/Azure SDK and MCP client libraries given how much of this milestone's work involved fixing MCP tool-calling response-format incompatibilities (suggesting version-sensitivity between Foundry's .NET MCP client and this repo's Python dispatcher).

## Missing Critical Features

**Read-only/least-privilege verification for Azure MCP discovery profile:**
- Problem: `BACKLOG.md` (HOG-010) specifies "Azure MCP discovery profile is read-only and namespace-filtered" as a requirement, but this pass did not verify the current Terraform role assignments (`local.azure_mcp_subscriptions`) actually enforce Reader-only access per subscription.
- Blocks: Confidence that the new managed-identity model (replacing SPN+AKV) doesn't over-provision write access across subscriptions.

## Test Coverage Gaps

**Live multi-tool-call agent turns (Foundry ↔ MCP ↔ APIM):**
- What's not tested: The full request/response shape of real Foundry Responses API tool-calling turns (`mcp_call`/`mcp_list_tools`/`message` output items), tool-error propagation format, and empty-string optional-argument handling.
- Files: `src/operations/foundry_agent.py`, `src/operations/mcp_server.py`, `src/operations/page_context.py`
- Risk: This exact class of bug (JWT null-ref, MAX_CALLS lifetime cap, empty-string validation rejection, tool-error crash) shipped past the full 1583-test suite and was only caught by manual live smoke testing in Phase 09-11. Recurrence risk is high for any future change to the tool-calling contract.
- Priority: High — add integration/contract tests using realistic (not idealized) Foundry response fixtures, including tool-error and empty-optional-argument cases.

**Terraform deploy-time env-var wiring:**
- What's not tested: Whether `deploy.sh` correctly threads every Terraform variable with operational significance (e.g., `apim_publisher_email`, `foundry_model_capacity`) end-to-end from `.env.local` through to `terraform apply`.
- Files: `scripts/deploy.sh`
- Risk: Silent reverts of manually-applied Azure quota/config changes on every deploy, as happened with the TPM quota this session.
- Priority: Medium — add a `terraform plan`-diff smoke check (e.g., a CI step that fails if a known-important variable is not explicitly passed).

**4 unidentified pre-existing failing tests:**
- What's not tested/known: STATE.md references "4 pre-existing failures in unrelated areas" without naming them.
- Files: Unknown — needs `uv run pytest -q` (or equivalent) to enumerate.
- Risk: Could mask a real regression if not tracked explicitly (i.e., a 5th new failure could go unnoticed if compared only against the vague "4 known" baseline).
- Priority: Medium — name and file-issue-track the 4 known failures so future runs can diff against an explicit list, not a count.

---

*Concerns audit: 2026-09-01*
