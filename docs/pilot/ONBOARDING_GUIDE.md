# Pilot Onboarding Guide

## What this platform is

AIOps Operations Graph (HOG) is an AIOps workbench that connects business
risk, technical dependencies, network paths, vulnerabilities, changes,
incidents, evidence, and Copilot reasoning into a single investigation
surface. It is **not** a static dashboard over a periodic snapshot: durable
semantic relationships (produced by the AIOps semantic engine) are composed
at request time with live/near-real-time operational sources (Azure Resource
Graph, Azure Monitor, Defender for Cloud, Update Manager, Sentinel/ITSM),
so what you see reflects current reality, not a stale export.

## Architecture summary (one paragraph)

A FastAPI backend (`src/api`) exposes a semantic graph API and several
composed workspaces (Investigation, Incident Command, Governed Remediation,
Compliance, Operational Twin, Multi-Agent Investigation) backed by
intelligence engines (network, vulnerability, patch, lifecycle, change,
incident causality, remediation planning) and a Fabric-published ontology.
A Next.js web workbench (`web/`) consumes the API. Azure AI Foundry provides
grounded Copilot narration over retrieved facts only — it never invents
data. Everything runs on Azure Container Apps, backed by a Fabric
OneLake-resident semantic graph rather than a separate database. See
`docs/architecture.md` and `docs/semantic-architecture.md` for the full
picture.

## Prerequisites

Before onboarding a pilot subscription, confirm:

- [ ] An Azure subscription (or set of subscriptions) with Reader-level
      Azure Resource Graph access available for a discovery SPN.
- [ ] An Entra tenant the pilot's users authenticate against, with the
      Entra app registration's audience/tenant configured
      (`AIOPS_ENTRA_TENANT_ID`, `AIOPS_ENTRA_AUDIENCE`).
- [ ] A Microsoft Fabric workspace + capacity (F2 minimum) for the
      semantic graph's durable state.
- [ ] An Azure AI Foundry project + governed prompt agent, if Copilot
      narration is in scope for the pilot (optional — the platform degrades
      to retrieval-only without it).
- [ ] Named business-service/application/environment/owner mappings for the
      pilot's in-scope workloads (used for scope-based RBAC and business
      context in every workspace).
- [ ] A named pilot customer sponsor and support rotation (see
      `SUPPORT_MODEL.md`'s RACI).
- [ ] Review and accept the known limitations disclosed in
      `SUPPORT_MODEL.md` (client-side-only saved state, no per-request audit
      log, no formal offboarding runbook yet).

## Onboarding steps

1. Provision infrastructure: `infra/scripts/deploy.sh` against the pilot's
   `.tfvars`, setting `alert_email_addresses` to the support rotation's
   address(es) and `purge_protection_enabled = true` on the Key Vault (see
   `SECURITY.md`).
2. Register the discovery connection(s):
   ```bash
   uv run aiops-inventory subscriptions add <connection-id> \
     --config /secure/config.yaml \
     --tenant-id "$TENANT_ID" \
     --subscription-id "$SUBSCRIPTION_ID" \
     --client-id "$CLIENT_ID" \
     --secret-ref "keyvault://<vault>/secrets/<name>" \
     --business-service "<Business Service>" \
     --application "<Application>" \
     --environment prod \
     --project-owner "<Owner>"
   ```
   (Full command reference: `docs/PRODUCTION_RUNTIME_ACTIVATION.md`.)
3. Activate and publish the first ontology generation:
   ```bash
   uv run aiops-inventory activate --config /secure/config.yaml \
     --fabric-config /secure/fabric.config.yaml --connection-id <connection-id>
   ```
4. Verify readiness: `GET /health` shows every configured provider `ready`,
   `GET /ready` returns 200.
5. Run `infra/scripts/validate-runtime-e2e.sh` against the live deployment.
6. Configure `AIOPS_API_GATEWAY_GRANTS` for the pilot's actual named users
   (reviewed per `SECURITY.md`'s checklist).
7. Walk the demo script (below) with the pilot customer sponsor before
   declaring onboarding complete.

## Demo script

A 20–30 minute walkthrough proving the end-to-end value chain:

1. **Executive Investigation Workspace** (`/investigate`) — start from a
   Business Service. Show it summarizes risk, evidence, topology, timeline,
   vulnerabilities, and impact in one place, in both Executive and Engineer
   modes. Shared entry links preserve all nine selected scope dimensions;
   a bookmark cannot widen the current operating scope. Malformed entry
   parameters fail before source reads. Changing the subject clears prior
   evidence while replacement sources load; late Copilot responses cannot
   publish into another subject, operating scope, or continuity generation.
   Narrowed bookmarks do not reuse or rebind a broader root conversation.
   The Team workspace disclosure saves server-backed navigation, immutable
   ownership, explicit reader/editor membership and reviewed revisions.
   Membership still requires independent platform access; revocation covers
   historical revisions. Applying saved navigation loads current evidence,
   not past provider conditions. Local saves remain browser-local fallbacks,
   and JSON exports include the effective scope; neither is team authorization.
   Current-signal counts describe the loaded subset, not a historical trend;
   unavailable incident or exposure sources do not imply quiet conditions.
2. **Drill into a real finding** — pick a live vulnerability or network gap
   surfaced for the pilot's actual subscription; show the evidence trail
   (which ARG/Defender/Update Manager record backs the claim) and the
   Copilot's grounded explanation (or retrieval-only summary if Foundry is
   not configured).
3. **Incident Command Workspace** (`/situations/[id]`) — show a correlated
   timeline combining alerts, changes, and CVE exposure for a real or
   simulated incident, with root-cause candidates and confidence.
4. **Compliance workspace** (`/compliance`) — show a posture violation (e.g.
   a firewall bypass or missing private endpoint) mapped to the owning
   business service.
5. **Governed Remediation Center** (`/remediation`) — show a remediation
   candidate generated from the finding above, with impact/rollback/
   validation, and the CAB-ready evidence pack.
6. **Operational Twin** (`/twin`) — show the same entity's current state,
   trend, and a scenario ("what if this firewall fails").
7. **Multi-Agent Investigation** (`/agents`) — pose a real operational
   question and show specialized agents' evidence-backed synthesis with
   human-in-the-loop controls (accept/reject a finding, request more
   evidence).
8. Close by re-affirming: every fact shown traces to a live/near-real-time
   Azure source (`DATA_SOURCES.md`), not a cached export.

## Acceptance criteria

The pilot is considered successfully demonstrating value when:

- [ ] An engineer can start from a real production incident/finding and
      reach a recommended remediation candidate without leaving the
      workbench, with every fact traceable to its source.
- [ ] An executive can understand business impact, owner, and required
      decision from the Investigation Workspace's Executive Mode without
      needing an engineer to translate.
- [ ] The Compliance workspace correctly identifies at least one real
      posture violation in the pilot's actual environment (not a synthetic
      fixture).
- [ ] `/health` and `/ready` remain accurate and truthful throughout the
      pilot (no "green" status while a provider is actually broken).
- [ ] No cross-scope data leakage is observed in any scoped-reader session.

## Feedback plan

- Weekly check-in with the pilot customer sponsor during the pilot window;
  structured feedback captured against the acceptance criteria above.
- Every reported issue is triaged per `SUPPORT_MODEL.md` and tracked to
  resolution or explicit deferral with rationale.
- A mid-pilot review (roughly the halfway point) revisits
  `READINESS_REVIEW.md` to confirm nothing has regressed.

## Exit criteria

The pilot concludes with one of:

- **Promote**: acceptance criteria met, no unresolved severity-1/2 issues,
  customer sponsor confirms value — proceed to broader rollout planning
  (additional subscriptions, formal SLA, closing the known-limitations gaps
  called out in `SUPPORT_MODEL.md`).
- **Extend**: partial success — specific acceptance criteria unmet with a
  clear remediation plan and a bounded extension window.
- **Stop**: acceptance criteria not met, or an unresolved security/data
  governance issue makes continuing unsafe — document why, offboard the
  pilot's connections and data per the (currently manual) offboarding
  procedure in `DATA_GOVERNANCE.md`, and capture lessons learned.
