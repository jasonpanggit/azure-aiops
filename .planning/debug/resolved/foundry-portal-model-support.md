---
status: resolved
trigger: "It still shows model not supported in foundry portal"
created: 2026-09-01T11:48:05+08:00
updated: 2026-09-01T12:21:00+08:00
---

# Debug Session: Foundry Portal Model Support

## Symptoms

- Expected: The deployed Foundry prompt agents using `gpt-5-mini` should show their Azure AI Search knowledge configuration as supported in the Foundry portal.
- Actual: The Foundry portal still displays "model not supported" for the agents' knowledge section.
- The same agent and Azure AI Search tool have already completed successfully through the Foundry Responses API and returned a grounded, cited result.
- The warning remains visible after adding the index integrated vectorizer and granting the search service identity access to the embedding deployment.
- Reproduction: Open a deployed specialist agent in the Foundry portal and inspect its Knowledge section.

## Eliminated

- hypothesis: The portal is reading a stale agent version or incomplete Search tool schema.
  evidence: All eight latest live versions contain the full-ID Search tool and match Terraform.
  timestamp: 2026-09-01T11:51:26+08:00
- hypothesis: Australia East, the AAD connection, or the integrated vectorizer is unsupported or unhealthy.
  evidence: Region matrix says Search=yes; connection has no error; both current and probe agents completed cited Search calls.
  timestamp: 2026-09-01T11:55:35+08:00
- hypothesis: The portal model compatibility metadata is stale.
  evidence: The portal warning exactly matches Microsoft Learn's current 2026-08-20 model/tool matrix (`gpt-5-mini`: Search=No, MCP=Yes).
  timestamp: 2026-09-01T11:55:35+08:00

## Evidence

- timestamp: 2026-09-01T11:50:09+08:00
  checked: `.planning/STATE.md` and working-tree baseline
  found: The investigation is an in-scope Foundry follow-up to completed phases 09-10/09-11; the repository already has many unrelated dirty and untracked files, while the relevant Foundry Terraform and agent-creation script have no tracked diff.
  implication: Any fix must be isolated to confirmed configuration and must not stage, overwrite, or clean the existing worktree.
- timestamp: 2026-09-01T11:50:40+08:00
  checked: `infra/terraform/foundry.tf` and `infra/scripts/create-foundry-agent.sh`
  found: Specialists are created as prompt agents on deployment `gpt-5-mini`; each receives `type=azure_ai_search` with the full project connection resource ID, index name, and `query_type=vector_semantic_hybrid`. Search, both Foundry identities, the integrated vectorizer identity, and deployer RBAC are explicitly provisioned.
  implication: The intended configuration is not missing the portal-visible Knowledge tool fields; live drift or a model allowlist remains to be tested.
- timestamp: 2026-09-01T11:51:26+08:00
  checked: Live ARM, Foundry Agent v1, Foundry connection, and Azure AI Search data-plane metadata
  found: All eight latest specialist versions are prompt agents on `gpt-5-mini` and include the same full-ID `azure_ai_search` tool; deployment `gpt-5-mini` version `2025-08-07` is Succeeded; the AAD CognitiveSearch connection has `error=null`; index `aiops-knowledge` has semantic configuration, HNSW profile, and an Azure OpenAI `text-embedding-3-small` vectorizer.
  implication: The live configuration matches Terraform and has no connection/resource error; a missing tool, stale agent version, failed deployment, or absent integrated vectorizer does not explain the warning.
- timestamp: 2026-09-01T11:54:00+08:00
  checked: Microsoft Learn source `articles/foundry/agents/concepts/limits-quotas-regions.md` and `how-to/tools/ai-search.md` at official `MicrosoftDocs/azure-ai-docs`
  found: The current matrix marks Australia East Azure AI Search support `yes`, but model `gpt-5-mini` has Azure AI Search `No` and MCP `Yes`. The Search how-to (dated 2026-08-21) uses `gpt-4.1-mini` for prompt agents, uses `gpt-5-mini` only in a hosted-agent/toolbox sample, and lists the deployed full connection ID and query type as valid.
  implication: Region and schema are supported, but the exact prompt-agent model/direct-tool combination is outside Microsoft’s documented compatibility contract; runtime success does not make it supported.
- timestamp: 2026-09-01T11:54:17+08:00
  checked: Official replacement rows, live Australia East model catalog/quota, and a fresh Responses API call to `aiops-network-agent`
  found: `gpt-5.4-mini` is GA with `agentsV2` and `responses`, and its matrix row supports both Azure AI Search and MCP; 2,850K TPM quota remains. The current `gpt-5-mini` call nevertheless completed `azure_ai_search_call`, returned the indexed 100-unit rule, and emitted a valid citation.
  implication: The warning is not stale—the current path is functional but explicitly unsupported. `gpt-5.4-mini` is the least disruptive supported successor and can be isolated-probed before cutover.
- timestamp: 2026-09-01T11:55:35+08:00
  checked: Temporary `gpt-5.4-mini` deployment and isolated prompt agent with the production Search connection/index/query type
  found: Deployment provisioned, agent definition resolved correctly, and Responses completed the Search call/output with the correct 100-unit fact and a `Network Design Standards` URL citation; the temporary agent and deployment were then deleted and absence verified.
  implication: The replacement model is deployable and the exact production Knowledge path works before managed-agent cutover.
- timestamp: 2026-09-01T11:56:28+08:00
  checked: Targeted Terraform plan after changing model defaults to `gpt-5.4-mini` version `2026-03-17`
  found: Exactly two managed resources change—chat deployment delete/create at the same 1,000K TPM capacity and `terraform_data.foundry_agent` replacement; no APIM, Search, application, or unrelated dirty resource appears.
  implication: The managed cutover is surgical and within the compatibility-fix scope.
- timestamp: 2026-09-01T11:57:07+08:00
  checked: First targeted apply attempt
  found: The deployment wrapper stopped before Terraform because unrelated `terraform.tfvars` requests a partially published container image tag; no Azure resources changed.
  implication: Do not build or deploy unrelated images. Passing `deploy_images=false` bypasses only that irrelevant preflight while the reviewed Terraform targets preserve model-only scope.
- timestamp: 2026-09-01T11:58:28+08:00
  checked: Exact saved Terraform plan apply
  found: Terraform replaced only `azurerm_cognitive_deployment.chat` and `terraform_data.foundry_agent`; result was `2 added, 0 changed, 2 destroyed`, with the new `gpt-5.4-mini` deployment created successfully and agent provisioning completed.
  implication: The supported-model fix is live without APIM, Search, application, or unrelated worktree changes.
- timestamp: 2026-09-01T11:58:49+08:00
  checked: Post-apply ARM deployment and Foundry v1 agent inventory
  found: `gpt-5.4-mini` version `2026-03-17` is Succeeded at the prior 1,000K TPM capacity. All eight specialists advanced one version, use `gpt-5.4-mini`, and retain `[mcp,mcp,azure_ai_search]`. Legacy `operations-copilot:4` remains on `gpt-5-mini` but has no tools and is not part of the warning or specialist cutover.
  implication: Every affected Knowledge-enabled agent now uses the documented supported model/tool combination; unrelated tool-less legacy metadata is correctly unchanged.
- timestamp: 2026-09-01T11:59:22+08:00
  checked: Direct post-cutover Responses API calls through the updated network specialist
  found: Model `gpt-5.4-mini` completed both `azure_ai_search_call`/output and `operations-mcp:network_topology`. Search returned the exact indexed 100-unit requirement with a `Network Design Standards` citation; MCP returned live topology evidence without an error.
  implication: Both tool classes required by every specialist work end-to-end after the compatibility cutover.
- timestamp: 2026-09-01T12:03:45+08:00
  checked: Full deployed-environment `scripts/evaluate_agents.py` fixed 10-case suite
  found: 10/10 cases completed with 0 errors, 0 timeouts, 100% routing, 100% narration, 100% tool correctness, and `microsoft-agent-framework` recorded for all cases.
  implication: The model cutover preserves the established cross-specialist production behavior beyond the focused Search/MCP probes.
- timestamp: 2026-09-01T12:04:28+08:00
  checked: Fix-acceptance guardrail
  found: Terraform fmt/validate and diff checks passed; no Stryker configuration exists for this Terraform/docs-only change; source-only revert mapped `gpt-5-mini` to official Search=No and reapply mapped `gpt-5.4-mini` to Search=Yes.
  implication: The fix is configuration-causal, valid, minimal, and not a behavior-deleting workaround.
- timestamp: 2026-09-01T12:05:01+08:00
  checked: Final cleanup and live audit
  found: All disposable plan/apply/evaluation artifacts and the probe resources are absent; `aiops-network-agent:15` remains on `gpt-5.4-mini` with two MCP tools and one Azure AI Search tool. Only the two intended source/doc files plus this session file remain from the investigation.
  implication: Self-verification is complete; only portal UI confirmation remains before resolution and archival.
- timestamp: 2026-09-01T12:06:23+08:00
  checked: Human verification checkpoint response
  found: The reported warning was observed before the model cutover; verification of the obsolete historical `gpt-5-mini` agent version is not required. The accepted non-browser oracle is the official compatibility matrix combined with latest-agent metadata and successful live Search/MCP calls.
  implication: Reconcile the current latest agent version against authoritative service metadata and current Microsoft documentation; archive if all three signals agree.
- timestamp: 2026-09-01T12:08:00+08:00
  checked: Current official MicrosoftDocs compatibility source and intended repository diff
  found: The current `MicrosoftDocs/azure-ai-docs` matrix still marks Australia East Azure AI Search=yes, `gpt-5-mini` Azure AI Search=No/MCP=Yes, and `gpt-5.4-mini` Azure AI Search=Yes/MCP=Yes. The relevant tracked diff remains limited to the Terraform model name/version defaults and matching infrastructure documentation.
  implication: The source fix still selects the documented portal-compatible combination and remains isolated from unrelated worktree changes.
- timestamp: 2026-09-01T12:10:00+08:00
  checked: Authoritative live Foundry v1 agent inventory and Azure Resource Manager deployment metadata
  found: `aiops-network-agent` reports latest version `15`, status `active`, prompt model `gpt-5.4-mini`, and exactly two MCP tools plus one full-ID Azure AI Search tool. ARM reports deployment `gpt-5.4-mini` version `2026-03-17`, `GlobalStandard`, provisioning state `Succeeded`, capacity 1,000K TPM.
  implication: The latest live agent—not historical version metadata—uses the exact model/tool combination that the current official matrix marks compatible.
- timestamp: 2026-09-01T12:13:00+08:00
  checked: Fresh latest-agent Foundry Responses calls
  found: The MCP prompt completed `operations-mcp:network_topology` with no response or tool error and returned a live topology fact. The Search prompt completed both `azure_ai_search_call` and `azure_ai_search_call_output` with no error and emitted five URL citations, but the newly worded "application units per spoke" question did not match the previously verified 100-unit rule.
  implication: Both latest-agent tool transports are live and successful. Re-run Search using the exact terminology in the indexed source to avoid conflating retrieval relevance with compatibility.
- timestamp: 2026-09-01T12:14:00+08:00
  checked: Canonical indexed knowledge source `infra/knowledge/network-design-standards.md`
  found: The 100-unit rule applies to priority headroom between adjacent firewall rule collections, not to application units per spoke.
  implication: The first fresh prompt used the wrong domain terms; a query about adjacent rule-collection priority headroom is the valid retrieval check.
- timestamp: 2026-09-01T12:16:00+08:00
  checked: Focused latest-agent Azure AI Search Responses call using canonical source terminology
  found: The response completed with no error, emitted completed `azure_ai_search_call` and `azure_ai_search_call_output` items, returned the exact 100-priority-unit headroom rule and rationale, and cited `Network Design Standards`.
  implication: The latest version's direct Azure AI Search path is working end-to-end with relevant grounded retrieval, complementing the successful fresh MCP call.
- timestamp: 2026-09-01T12:18:00+08:00
  checked: All-specialist latest-version compatibility audit
  found: The authoritative Foundry v1 inventory returns all eight specialists active on their latest versions (15 or 16), each using `gpt-5.4-mini` with exactly two MCP tools and one Azure AI Search tool.
  implication: The supported model/tool tuple is consistent across every affected current agent; any portal inspection must open these latest versions rather than historical `gpt-5-mini` versions.
- timestamp: 2026-09-01T12:21:00+08:00
  checked: Final pre-commit validation and worktree scope
  found: `terraform fmt -check`, `terraform validate`, and scoped `git diff --check` pass. The source diff remains exactly two model/version substitutions across `infra/terraform/variables.tf` and `infra/README.md`; unrelated dirty files remain unstaged.
  implication: The archived fix is valid and can be committed without absorbing unrelated worktree changes.

## Resolution

root_cause: The specialists use `gpt-5-mini`, which Microsoft explicitly supports for MCP and Responses but not for the direct Azure AI Search prompt-agent tool; the portal warning correctly reports that unsupported model/tool combination even though the backend currently executes it successfully.
fix: Updated the managed prompt-agent model defaults from `gpt-5-mini` `2025-08-07` to supported GA `gpt-5.4-mini` `2026-03-17` and applied the model/agent-only Terraform cutover.
verification:
  target_test:
    result: pass
    evidence: Direct Search and MCP Responses completed on `gpt-5.4-mini`; full evaluation passed 10/10.
  mutation_check:
    result: skipped
    reason_if_skipped: No mutation framework or executable mutation site applies to Terraform scalar defaults and a matching README entry.
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: false
    evidence: Diff replaces model name/version and documentation only; it does not delete or bypass behavior.
  adjacent_tests:
    result: pass
    suites_run:
      - terraform fmt -check
      - terraform validate
      - scripts/evaluate_agents.py (10 live cases)
  portal_compatibility_contract:
    result: pass
    evidence: Current Microsoft model/tool matrix marks `gpt-5.4-mini` Azure AI Search=Yes and MCP=Yes; all eight latest live agent versions use that tuple; fresh latest-agent Search and MCP Responses completed without errors.
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    evidence: Reverted source selected matrix Search=No `gpt-5-mini`; reapplied source selected Search=Yes `gpt-5.4-mini`.
  guardrail_verdict: accepted
oracle_type: derived
files_changed:
  - infra/terraform/variables.tf
  - infra/README.md

## Prevention

- branching_5_whys:
    config:
      - The portal warned because the managed prompt agents selected `gpt-5-mini` with direct Azure AI Search.
      - That tuple was outside Microsoft's documented model/tool compatibility contract even though the data plane still executed it.
      - The Terraform default treated successful runtime execution as sufficient evidence of support and therefore preserved the unsupported tuple.
    verification:
      - Existing live evaluations asserted successful responses, routing, and tool correctness, not portal compatibility metadata.
      - No gate compared the selected prompt-agent model and attached tools against Microsoft's current compatibility matrix.
    environment_and_data:
      - Australia East, the Search connection/index/vectorizer, and latest agent schemas were healthy and supported, so they did not contribute.
    and_gate: "no—the unsupported model default alone caused the deterministic portal warning"
- why_not_caught: No gate existed for Foundry portal model/tool compatibility; runtime Search success could not detect a combination that works on the data plane but is explicitly unsupported by the portal contract.
- recurrence_guard: The config-default change in `infra/terraform/variables.tf` now selects `gpt-5.4-mini` `2026-03-17`, whose current official matrix row supports both Azure AI Search and MCP; this knowledge-base pattern records that runtime success is not a substitute for compatibility-matrix validation.

## Current Focus

- hypothesis: Confirmed—the current latest Knowledge-enabled agent versions are portal-compatible because they use a model that Microsoft's current matrix supports for both Azure AI Search and MCP.
- test: Accepted derived contract oracle: official compatibility matrix plus authoritative latest-agent/deployment metadata plus successful fresh Search/MCP Responses.
- expecting: Satisfied for all eight current specialists.
- next_action: Commit only `infra/terraform/variables.tf` and `infra/README.md`, then commit this resolved session and its knowledge-base entry through the GSD docs commit helper.
- bug_class: bohrbug
- reasoning_checkpoint:
    hypothesis: The selected prompt-agent model is outside the direct Azure AI Search compatibility matrix.
    confirming_evidence: Microsoft marks `gpt-5-mini` Search=No/MCP=Yes; all live schemas are healthy; an isolated supported-model probe grounded and cited correctly.
    falsification_test: An identical `gpt-5.4-mini` prompt-agent/Search probe would fail or lack a citation; it instead completed successfully.
    fix_rationale: Move to the closest GA mini-tier successor explicitly supporting both required tools, without changing connections, indexes, prompts, or application code.
    blind_spots: Portal rendering cannot be browser-automated here; model quality and all eight tool allocations must be checked after cutover.
    candidate_causes:
      code: Portal compatibility lookup could be stale, contradicted by the current official matrix.
      config: `foundry_model_name=gpt-5-mini` selects an unsupported direct Search combination; confirmed.
      environment: Australia East could lack Search support, contradicted by the region matrix and successful probe.
      data: Old agent versions or malformed tool metadata could trigger the warning, contradicted by all latest live definitions.
    and_gate: "no—model selection alone explains the deterministic warning; region, resource health, and metadata are valid"
- tdd_checkpoint: null
