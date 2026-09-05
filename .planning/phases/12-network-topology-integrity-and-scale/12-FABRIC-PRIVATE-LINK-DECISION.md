# Phase 12 Private Link Semantics Decision

**Date:** 2026-09-06  
**Status:** Confirmed from current official Microsoft documentation  
**Resume signal:** `fabric: mixed - tenant/workspace scoped, not capacity scoped; cognitive: per-resource; icons: available for Cognitive Services, unavailable for Fabric in Azure Public Service Icons V21`

## Evidence

### Microsoft Fabric

Microsoft Fabric supports private links at the tenant and workspace levels, not on individual `Microsoft.Fabric/capacities` resources.

- [About private links for secure access to Fabric](https://learn.microsoft.com/en-us/fabric/security/security-private-links-overview) states that Fabric supports tenant-level and workspace-level private links.
- [Set up and use a tenant-level private link](https://learn.microsoft.com/en-us/fabric/security/security-private-links-use) creates a global `Microsoft.PowerBI/privateLinkServicesForPowerBI` resource for the Fabric tenant.
- [Overview of workspace-level private links](https://learn.microsoft.com/en-us/fabric/security/security-workspace-level-private-links-overview) states that each workspace has its own private-link service and that a workspace private-link endpoint cannot access non-workspace resources such as capacities.

Therefore, absence of a private endpoint directly targeting a Fabric capacity is not evidence that the supported Fabric private-link control is missing.

### Microsoft Cognitive Services / Foundry Tools

[Configure virtual networks for Foundry Tools](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks#use-private-endpoints) documents private endpoints for an individual Foundry Tools resource. The private endpoint uses an address from the virtual network for that resource, and the account can disable public endpoint access.

Therefore, a missing private endpoint remains a legitimate per-resource finding for `Microsoft.CognitiveServices/accounts`.

### Official icons

- [Azure architecture icons](https://learn.microsoft.com/en-us/azure/architecture/icons/) is the official source required by `web/public/azure-icons/README.md`.
- The official Azure Public Service Icons V21 archive contains `10162-icon-service-Cognitive-Services.svg`.
- The V21 archive contains no Microsoft Fabric product icon. The similarly named Managed Service Fabric and Service Fabric Cluster icons represent Azure Service Fabric and must not be substituted.
- Microsoft publishes a separate [Microsoft Fabric icon collection](https://learn.microsoft.com/en-us/fabric/fundamentals/icons), but it is outside the V21 source set currently declared by this repository.

## Disposition

| Resource type | Project node | Missing-private-endpoint gap | Required qualification |
| --- | --- | --- | --- |
| `Microsoft.Fabric/capacities` | Yes. Render once as a Fabric workload/private-link candidate. | **Do not emit the per-capacity `missing_private_endpoint` gap.** The asserted control is not supported at capacity scope. Apply this correction in the gap payload so every consumer receives the same truthful result; no drawer badge should be synthesized for the suppressed false positive. | Add a node fact indicating that Fabric private-link posture is evaluated at tenant or workspace scope. Later drawer/export surfaces must repeat that scope without claiming that the capacity itself is privately linked. |
| `Microsoft.CognitiveServices/accounts` | Yes. Render once as an Azure AI Services / Foundry Tools workload/private-link candidate. | Keep the existing per-resource `missing_private_endpoint` finding and severity unchanged. | No additional qualification beyond the existing public-network-access and endpoint facts. |

## Icon Directive

- Add the unmodified V21 Cognitive Services SVG as `ai-services.svg` and list it in the icon README.
- Do not add `fabric.svg` from an unrelated service or a different icon source. Record that Fabric is intentionally icon-less because V21 has no Fabric product glyph.
- Do not add an npm icon package.

## Downstream Directive for Plan 12-06

Plan 12-06 must project both resource types, suppress the false per-capacity Fabric endpoint gap at the server gap payload, preserve the Cognitive Services finding, add the Fabric scope qualification to node details, install only the V21 Cognitive Services icon, and use the existing icon-less tile for Fabric.

## Research Assumptions Resolved

- **A1:** Resolved. The assumption that Fabric capacity private-link posture is per-resource is false; the supported controls are tenant- and workspace-scoped.
- **A4:** Resolved partially. Cognitive Services has an official V21 icon; Microsoft Fabric does not have one in V21 and must use the declared icon-less fallback.

