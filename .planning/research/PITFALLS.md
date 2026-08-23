# Domain Pitfalls

**Domain:** AI-assisted Azure cloud operations platform  
**Project:** Azure AI Operations Platform  
**Analysis date:** 2026-08-23  
**Overall confidence:** MEDIUM (official guidance was cross-checked, while several implementation-specific risks are inferred from the existing codebase map)

## Critical Pitfalls

### 1. Fluent explanations outrun the evidence

**What goes wrong:** The operations agent or Foundry narrator produces a plausible root cause, causal chain, severity, or remediation rationale that is not supported by the current Azure/Fabric facts. A correct-looking answer can cause an operator to ignore the real incident or approve an unnecessary change.

**Why it happens:** The language model is optimized for coherent completion, not truth; retrieved context may be incomplete, contradictory, or too old. The repository already has both immutable semantic snapshots and live providers, which creates a risk that the model blends them without making the distinction clear.

**Warning signs:**
- Explanation claims a cause or dependency that has no evidence ID, source timestamp, or matching graph relationship.
- The answer uses definitive language while evidence is stale, unavailable, or conflicting.
- Recommendation fields are populated when the evidence set is empty or only contains derived assertions.
- Operators cannot reproduce the answer from the cited snapshot generation and query scope.

**Prevention:**
- Make an evidence bundle a required input to explanation and recommendation generation; require every material claim to reference source record(s), freshness, scope, and quality status.
- Separate observed facts, derived inferences, hypotheses, and proposed actions in the response schema.
- Refuse or downgrade explanations when freshness/quality gates fail; do not silently fall back from live data to an old snapshot.
- Add deterministic claim-evidence validation and evaluation fixtures for unsupported, contradictory, and missing-evidence cases.
- Keep Foundry as a narrator of already retrieved facts, not an authority that can query or mutate Azure on its own.

**Roadmap phase:** Phase 1 — Evidence-backed situation workflow (before recommendation or remediation).

### 2. Stale, partial, or silently degraded evidence is treated as current

**What goes wrong:** A sync failure, expired provider refresh, incomplete ARG page set, stale vulnerability feed, or partially published Fabric projection is presented as a complete operational twin. The operator makes a decision based on an estate view that is missing the resource or change that matters.

**Why it happens:** Multiple replicas have process-local refresh state; large syncs can outlive the remote lease; the current map identifies fallback full-table freshness scans and incomplete failure-injection coverage. Snapshot systems also encourage consumers to treat a valid generation as current without checking age and completeness.

**Warning signs:**
- “Healthy/current” responses have no freshness timestamp, generation, source coverage, or last successful sync.
- Failed or interrupted ingestion advances a watermark or changes `current`.
- Different API replicas report materially different freshness.
- A provider timeout returns an empty collection indistinguishable from “no findings.”
- ARG pagination approaches its ceiling or a dataset quality report contains dropped/unknown records.

**Prevention:**
- Attach freshness, completeness, source coverage, generation ID, and quality warnings to every situation and evidence bundle.
- Use explicit `fresh`, `stale`, `degraded`, and `unavailable` states; never encode provider failure as an empty successful result.
- Publish only complete immutable generations, keep success watermarks unchanged on failure, and add recovery/reconciliation checks after every Fabric/ontology stage.
- Coordinate refresh and lease renewal across replicas; model long-running syncs as durable jobs rather than request-local or process-local work.
- Set domain-specific maximum evidence ages and block write recommendations when they are exceeded.

**Roadmap phase:** Phase 1 — Evidence and data-quality contract; Phase 4 — Pilot reliability and distributed refresh hardening.

### 3. Unsafe remediation crosses from recommendation into execution

**What goes wrong:** A model-generated action changes production resources, broadens access, deletes or restarts the wrong target, or executes a malformed command. “Recommended” is accidentally wired to “run,” or a retry repeats a non-idempotent action.

**Why it happens:** Natural-language actions hide blast radius and preconditions. Resource identity, subscription scope, current state, and rollback semantics can change between analysis and approval. Timeouts can leave an action running while the caller believes it was cancelled.

**Warning signs:**
- A recommendation contains free-form executable text rather than a typed action and validated target.
- Approval is attached to a conversational turn instead of an immutable action version and exact parameter set.
- There is no dry-run/impact preview, policy decision, expiry, idempotency key, or post-action verification.
- Execution success means only that a request was submitted, not that the intended resource state was reached.
- A timeout or client disconnect leaves an unknown action status.

**Prevention:**
- Use an allowlisted typed action catalog with explicit target resolution, scope, preconditions, blast-radius estimate, timeout, and rollback/compensation plan.
- Keep analysis, approval, dispatch, and verification as separate state transitions; require a fresh preflight immediately before dispatch.
- Enforce policy outside the model and outside the UI; the executor must reject actions without valid approval, matching evidence, and an unexpired action hash.
- Prefer idempotent operations, durable job status, cooperative cancellation, bounded retries, and post-action read-back verification.
- Start with dry-run and reversible low-risk actions; maintain a kill switch and per-subscription/resource budgets.

**Roadmap phase:** Phase 2 — Recommendation, approval, and bounded execution.

### 4. Identity, scope, or privilege mistakes authorize the wrong operator

**What goes wrong:** A user sees or changes another business service’s resources, a forged gateway header becomes an operator identity, or the application identity can enumerate/delete more secrets or resources than the workflow requires.

**Why it happens:** This platform combines Entra JWTs, trusted gateway assertions, managed identities, Key Vault, Fabric, Resource Graph, nested provider responses, and subscription/business-service filtering. Authorization is both action gating and row-level projection; a new response shape can bypass one layer.

**Warning signs:**
- Header-based auth is reachable without a validating gateway.
- Authorization tests cover route access but not nested fields, subscription combinations, or empty/unrestricted scopes.
- The same identity can read secrets, execute remediation, publish data, and administer infrastructure.
- Resource IDs are accepted from the client without server-side scope resolution.
- A new provider or intelligence response is returned before scope filtering.

**Prevention:**
- Prefer direct Entra JWT validation in production or cryptographically bound gateway assertions; make trusted-header mode impossible on direct public ingress.
- Enforce tenant, subscription, resource-group, business-service, and action scope server-side immediately after provider retrieval and again before execution.
- Resolve target identity from authoritative Azure IDs; never trust display names or model-selected scope.
- Separate reader, publisher, secret-writer, and remediation identities; use managed identity and least privilege, with deny-by-default permissions.
- Add integration tests for forged headers, cross-scope leakage, privilege escalation, and every newly introduced nested response shape.

**Roadmap phase:** Phase 3 — Security boundary, authorization, and pilot identity review.

### 5. Prompt injection becomes tool abuse or data exfiltration

**What goes wrong:** An incident description, resource tag, ticket, vulnerability record, or external document contains instructions that redirect the model. The model discloses cross-scope context, fabricates approval, invokes an unsafe tool, or sends sensitive operational data to the external AI service.

**Why it happens:** Retrieved operational text is untrusted input, yet it is often placed near instructions in a prompt. Tool outputs can be treated as authoritative, and model-side refusal is not a security boundary. The existing Foundry integration sends retrieved operational context externally, increasing the impact of scope or prompt mistakes.

**Warning signs:**
- Untrusted fields contain “ignore previous instructions,” role claims, links, or action requests and the model follows them.
- Tools accept arbitrary resource IDs, URLs, commands, or natural-language action arguments.
- Tool results are fed back without provenance, size limits, field classification, or revalidation.
- A model response can grant itself approval, change authorization state, or call a write-capable tool.
- Prompt logs or telemetry contain secrets, tokens, or unnecessarily broad estate data.

**Prevention:**
- Treat all source records, search results, MCP responses, and tool outputs as data, never as instructions; delimit and label them explicitly.
- Use separate instruction and evidence channels where supported, content-filter/prompt-shield untrusted text, and red-team direct and indirect injection cases.
- Give the model read-only, narrow, typed tools; perform authorization, target validation, URL/command allowlisting, and output schema validation in ordinary code.
- Minimize and classify outbound context immediately before Foundry; redact secrets and enforce tenant/business-service scope at that boundary.
- Require a human approval record from a trusted control plane; model text cannot create, alter, or satisfy approval.

**Roadmap phase:** Phase 3 — AI security boundary and tool governance (before any write-capable integration).

### 6. Approval is cosmetic or bypassable

**What goes wrong:** A user approves one explanation but the system executes a changed target or regenerated action; an API, retry path, CLI, background worker, or privileged service bypasses the UI approval; approval is inherited after evidence becomes stale.

**Why it happens:** Approval is implemented as a frontend button or boolean instead of a server-enforced state machine. Multi-replica/process-local state and asynchronous execution make it easy for the displayed state and durable execution state to diverge.

**Warning signs:**
- Approval is stored only in browser state, a prompt, or a mutable row without an action hash.
- The execution endpoint accepts a resource/action payload independently of the approved proposal.
- Approver identity, reason, timestamp, expiry, and policy decision are absent.
- The same principal can propose, approve, and execute high-impact changes without separation of duties.
- Approval remains valid after evidence, target state, or policy changes.

**Prevention:**
- Define a durable state machine: proposed → preflighted → approved → dispatched → verified/failed/expired, with illegal transitions rejected server-side.
- Bind approval to an immutable proposal hash, exact target/parameters, evidence generation, policy result, and expiry; re-preflight before dispatch.
- Enforce approval at every execution surface (API, worker, CLI, retry), with separation of duties for high-risk actions.
- Make approval and execution records append-only and correlate them to request, job, resource, and provider operation IDs.

**Roadmap phase:** Phase 2 — Approval and execution state machine; Phase 3 — authorization/security verification.

### 7. Audit history cannot reconstruct what happened

**What goes wrong:** The team cannot prove which facts the model saw, which model/prompt/version produced a recommendation, who approved it, what identity executed it, or whether Azure reached the intended state. This blocks incident review, compliance, rollback, and learning.

**Why it happens:** Ordinary request logs capture status and latency but not a durable, privacy-safe decision record. External AI calls, asynchronous jobs, retries, post-commit sync stages, and provider failures are not consistently correlated.

**Warning signs:**
- Audit records contain only free-text output or a final success flag.
- Evidence, prompt/model version, policy result, approval, dispatch, and verification cannot be joined by one correlation ID.
- Logs contain sensitive prompts but omit action parameters or target identity.
- Failed rollback or partial Fabric publication has no operator-visible event.
- Records are mutable, deletable by the application identity, or retained for less time than the operational risk window.

**Prevention:**
- Define an append-only audit event schema for detection, evidence assembly, explanation, recommendation, policy evaluation, approval, dispatch, provider operation, verification, and failure.
- Store hashes/references to prompts and evidence rather than unnecessary sensitive payloads; record model/version, configuration, code release, freshness, and scope.
- Propagate correlation and job IDs through API, ARG, Fabric, Key Vault, Foundry, and Azure operation calls; alert on missing or anomalous audit events.
- Restrict audit mutation/deletion and document retention, access, residency, and redaction requirements.

**Roadmap phase:** Phase 2 — End-to-end workflow audit contract; Phase 4 — production observability and governance.

### 8. Drift invalidates policy, ontology, and action assumptions

**What goes wrong:** Azure APIs, resource schemas, RBAC assignments, prompt/model behavior, Terraform configuration, or the Fabric ontology changes while the platform still assumes the old contract. The system may silently omit resources, misclassify exposure, or execute against an unexpected shape.

**Why it happens:** The platform materializes governed projections rather than replacing systems of record; derived graph identity and response models therefore drift. Configuration is spread across environment variables and Terraform, and external CLI/extensions are mutable dependencies.

**Warning signs:**
- Unknown fields, resource types, relationship IDs, or permissions are silently dropped.
- Ontology validation passes while source coverage or schema version changes.
- Production configuration starts in a degraded mode because mandatory settings are not validated together.
- A provider/model/CLI upgrade changes outputs without regression evaluation.
- Policy decisions are based on a cached role or stale resource state.

**Prevention:**
- Version schemas, ontology mappings, action contracts, prompts, models, and policy bundles; fail closed on incompatible versions.
- Preserve unknown records in quarantine/quality reports, monitor coverage deltas, and run contract tests against representative Azure fixtures.
- Revalidate policy and resource state immediately before writes; use feature flags and staged upgrades.
- Centralize typed startup/deployment configuration and pin external tool/provider versions with a tested upgrade process.

**Roadmap phase:** Phase 4 — pilot hardening, drift detection, and operational governance.

## Moderate Pitfalls

### 9. Noisy detections and alert fatigue erode trust

**What goes wrong:** Repeated low-value situations, duplicate findings from multiple feeds, unstable severity, or unbounded “possible causes” train operators to dismiss the workbench. A suppression intended for one resource hides a broader incident.

**Warning signs:**
- High alert volume with low acknowledgement or action rate.
- Identical situations lack stable fingerprints and deduplication windows.
- Severity changes without a material evidence change.
- Suppression has no owner, expiry, reason, or blast-radius display.

**Prevention:**
- Define stable situation identity, deduplication, grouping, suppression expiry, and evidence-based severity recalculation.
- Measure precision, duplicate rate, acknowledgement time, stale rate, and false-positive feedback by domain.
- Show uncertainty and competing hypotheses; route low-confidence findings to review rather than escalating them as incidents.
- Make suppression scoped, auditable, reversible, and visible in health summaries.

**Roadmap phase:** Phase 1 — situation detection and evidence UX; Phase 4 — pilot tuning and feedback loops.

### 10. Pilot rollout creates production risk before readiness is proven

**What goes wrong:** A broad Azure pilot launches with write capability, uncalibrated detections, incomplete identity coverage, no rollback rehearsal, or no clear owner. Early false positives or one unsafe recommendation destroys operator confidence and causes the pilot to be disabled.

**Warning signs:**
- Pilot success is measured by usage or number of actions rather than safety, precision, recovery, and operator outcomes.
- No shadow/read-only baseline, canary scope, stop conditions, or rollback runbook exists.
- Representative incident, vulnerability, compliance, and exposure scenarios are absent.
- Operators have not rehearsed stale data, provider outage, partial sync, denied approval, and failed remediation.
- Production traffic, secrets, and external AI retention/residency have not been reviewed.

**Prevention:**
- Start in read-only/shadow mode with a known-good baseline; compare detections and explanations to human decisions.
- Canary one subscription or low-risk resource class, then expand only against explicit entry/exit criteria and error budgets.
- Keep remediation disabled by default; enable only allowlisted reversible actions after dry-run and rollback drills.
- Establish named service ownership, on-call escalation, training, privacy/security review, and a one-command kill switch.
- Capture operator feedback and post-incident learning as versioned evaluation cases before widening scope.

**Roadmap phase:** Phase 4 — controlled Azure pilot and operational readiness.

## Minor Pitfalls

### 11. Partial failure is mistaken for cancellation or success

**What goes wrong:** A request timeout returns while worker threads continue, a retry duplicates work, or a post-commit Fabric failure leaves an apparently successful but inconsistent state.

**Warning signs:** “Cancelled” jobs have downstream activity; status is request-local; no durable reconciliation exists after process termination.

**Prevention:** Use durable job records, cooperative cancellation, idempotency keys, explicit unknown/intermediate states, and reconciliation after every external operation.

**Roadmap phase:** Phase 2 — durable workflow jobs; Phase 4 — failure-injection and recovery testing.

### 12. Sensitive context leaks through diagnostics and evaluation

**What goes wrong:** Prompts, tool results, resource metadata, or model evaluation fixtures expose secrets or broad estate details through logs, traces, screenshots, or external evaluation services.

**Warning signs:** Raw prompts in logs; shared fixtures containing live IDs; telemetry lacks field classification and retention controls.

**Prevention:** Redact at source, use synthetic fixtures, minimize outbound context, restrict audit access, and test log/export paths as part of privacy review.

**Roadmap phase:** Phase 3 — AI/data security review.

## Phase-Specific Warnings

| Phase topic | Likely pitfall | Mitigation |
|---|---|---|
| Situation detection and evidence | Hallucinated explanations, stale/partial data, noisy detections | Evidence IDs and freshness gates; degraded states; stable fingerprints; evaluation fixtures |
| Recommendation and approval | Unsafe remediation, cosmetic approval, partial failure | Typed action catalog; immutable proposal hash; server-side state machine; durable jobs; dry-run |
| Identity and AI security | Scope leakage, privilege mistakes, prompt injection/tool abuse | Entra/gateway boundary tests; least privilege; typed read-only tools; outbound minimization; red-team cases |
| Controlled pilot and hardening | Drift, audit gaps, alert fatigue, rollout risk | Append-only audit; canary/shadow rollout; kill switch; rollback drills; schema/policy/version monitoring |

## Sources

Official and primary guidance was checked on 2026-08-23. Source confidence is **MEDIUM** after cross-checking official guidance; implementation-specific observations are additionally grounded in `.planning/codebase/CONCERNS.md` and `.planning/codebase/ARCHITECTURE.md`.

- Microsoft Learn, Prompt engineering techniques: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/prompt-engineering (MEDIUM)
- Microsoft Learn, Prompt Shields in Azure AI Content Safety: https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection (MEDIUM)
- Microsoft Azure Well-Architected Framework, Identity and access management: https://learn.microsoft.com/en-us/azure/well-architected/security/identity-access (MEDIUM)
- Microsoft Azure Well-Architected Framework, Monitoring workload reliability: https://learn.microsoft.com/en-us/azure/well-architected/reliability/monitoring (MEDIUM)
- NIST, AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework (MEDIUM)
- NIST, Generative AI Profile: https://www.nist.gov/itl/ai-risk-management-framework/ai-rmf-generative-ai-profile (MEDIUM)
- Google SRE Book, Embracing risk: https://sre.google/sre-book/embracing-risk/ (MEDIUM)
- Repository codebase concerns and known security/test gaps: `.planning/codebase/CONCERNS.md` (HIGH for repository-specific observations)
- Repository architecture and data-flow constraints: `.planning/codebase/ARCHITECTURE.md` (HIGH for repository-specific observations)
