# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## foundry-portal-model-support — Foundry portal rejected the prompt-agent model for Azure AI Search
- **Date:** 2026-09-01
- **Error patterns:** model not supported, Foundry portal, gpt-5-mini, Azure AI Search, Knowledge section
- **Root cause(s):** The specialists used `gpt-5-mini`, which Microsoft supports for MCP and Responses but not for the direct Azure AI Search prompt-agent tool; the portal correctly reported the unsupported model/tool combination even though the backend executed it successfully.
- **Fix:** Updated the managed prompt-agent model defaults to supported GA `gpt-5.4-mini` `2026-03-17` and applied the model/agent-only Terraform cutover.
- **Files changed:** infra/terraform/variables.tf, infra/README.md
- **Why not caught:** No gate existed for Foundry portal model/tool compatibility; runtime Search success could not detect a combination that works on the data plane but is explicitly unsupported by the portal contract.
- **Recurrence guard:** The config-default change in `infra/terraform/variables.tf` selects `gpt-5.4-mini` `2026-03-17`, whose current official matrix row supports both Azure AI Search and MCP; this KB pattern records that runtime success is not a substitute for compatibility-matrix validation.
---
