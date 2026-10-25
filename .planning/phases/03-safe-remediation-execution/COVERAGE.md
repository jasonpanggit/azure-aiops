# API Coverage — Azure Resource Manager patch execution

> Full coverage by default for the Azure API capabilities in Phase 03. Any
> excluded API surface is an explicit, reasoned opt-out.

| capability | decision | reason |
|---|---|---|
| Azure Resource Manager access token acquisition | INTEGRATE | Required to authenticate the bounded ARM operations below. |
| Azure Compute `virtualMachines/installPatches` for one approved Azure VM target | INTEGRATE | Implements the exact, approval-bound patch selection for Azure VMs. |
| Hybrid Compute `machines/installPatches` for one approved Arc server | INTEGRATE | Implements the exact, approval-bound patch selection for Arc-enabled servers. |
| Container Service `agentPools/upgradeNodeImageVersion` for one approved AKS pool | INTEGRATE | Implements the bounded node-image upgrade for one identified pool. |
| Read the Azure long-running-operation URL returned by a submitted execution | INTEGRATE | Required to record a verified terminal outcome; submission acceptance alone is not success. |
| Other Azure Resource Manager mutation APIs | OPT-OUT | Only bounded VM/Arc patch and AKS node-image actions are allowed; arbitrary mutations are out of scope. |
| Azure Update Manager assessment and patch-discovery APIs | OPT-OUT | Phase 03 consumes the existing patch inventory/assessment projection and does not introduce a new assessment acquisition path. |
| Azure resource creation, deletion, configuration, or rollback APIs | OPT-OUT | Phase 03 does not provision resources or perform automated rollback; rollback guidance is informational only. |
| Azure Resource Graph, Microsoft Graph, and unrelated service APIs | OPT-OUT | These surfaces are not required by the Phase 03 remediation execution workflow. |
