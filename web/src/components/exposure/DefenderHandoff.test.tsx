import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DEFENDER_PORTAL_ACTION_LABELS,
  DefenderHandoff,
  safeDefenderPortalHref,
  type DefenderPortalAction,
} from "./DefenderHandoff";

const VM_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1";
const REGISTRY_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/acr-1";
const CLUSTER_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-1";

const actions: DefenderPortalAction[] = [
  {
    kind: "open_defender_alert",
    href: "https://portal.azure.com/#view/Microsoft_Azure_Security/AlertBlade/alertId/alert-1",
    evidenceId: "alert-1",
  },
  {
    kind: "open_defender_attack_path",
    href: "https://portal.azure.com/#view/Microsoft_Azure_Security/AttackPathBlade/attackPathId/path-1",
    evidenceId: "path-1",
  },
  {
    kind: "open_defender_recommendation",
    href: "https://portal.azure.com/#view/Microsoft_Azure_Security/RecommendationBlade/assessmentKey/assessment-1",
    evidenceId: "assessment-1",
  },
  {
    kind: "open_azure_resource",
    href: `https://portal.azure.com/#resource${VM_ID}/overview`,
    resourceId: VM_ID,
    evidenceId: "resource-evidence-1",
  },
  {
    kind: "open_registry",
    href: `https://portal.azure.com/#resource${REGISTRY_ID}/overview`,
    resourceId: REGISTRY_ID,
    evidenceId: "registry-evidence-1",
  },
  {
    kind: "open_cluster",
    href: `https://portal.azure.com/#resource${CLUSTER_ID}/overview`,
    resourceId: CLUSTER_ID,
    evidenceId: "cluster-evidence-1",
  },
];

describe("DefenderHandoff", () => {
  it("renders the six named handoffs with exact labels, evidence, and safe new-tab semantics", () => {
    render(
      <DefenderHandoff
        actions={actions}
        authorizedResourceIds={[VM_ID, REGISTRY_ID, CLUSTER_ID]}
      />,
    );

    expect(DEFENDER_PORTAL_ACTION_LABELS).toEqual({
      open_defender_alert: "Open alert in Defender for Cloud",
      open_defender_attack_path: "Open attack path in Defender for Cloud",
      open_defender_recommendation:
        "Open recommendation in Defender for Cloud",
      open_azure_resource: "Open affected resource in Azure portal",
      open_registry: "Open registry in Azure portal",
      open_cluster: "Open cluster in Azure portal",
    });

    for (const action of actions) {
      const label = DEFENDER_PORTAL_ACTION_LABELS[action.kind];
      const link = screen.getByRole("link", {
        name: `${label} (opens Azure portal in a new tab)`,
      });
      expect(link).toHaveAttribute("href", action.href);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getByText(`Evidence ID: ${action.evidenceId}`)).toBeInTheDocument();
    }
    expect(
      screen.getAllByText("Opens Azure portal in a new tab."),
    ).toHaveLength(actions.length);
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,unsafe",
    "http://portal.azure.com/#view/Microsoft_Azure_Security/AlertBlade/alertId/1",
    "/#view/Microsoft_Azure_Security/AlertBlade/alertId/1",
    "https://portal.azure.com.evil.example/#view/Microsoft_Azure_Security/AlertBlade/alertId/1",
    "https://portal.azure.com@evil.example/#view/Microsoft_Azure_Security/AlertBlade/alertId/1",
    "https://attacker@portal.azure.com/#view/Microsoft_Azure_Security/AlertBlade/alertId/1",
    "https://portal.azure.com/#view/Unknown/AlertBlade/alertId/1",
    "https://portal.azure.com/#view/Microsoft_Azure_Security/AttackPathBlade/attackPathId/1",
  ])("rejects an unsafe or action-mismatched Defender alert URL: %s", (href) => {
    expect(
      safeDefenderPortalHref({
        kind: "open_defender_alert",
        href,
        evidenceId: "alert-unsafe",
      }),
    ).toBeNull();
  });

  it("requires a canonical resource route that exactly matches an authorized ARM ID", () => {
    const action: DefenderPortalAction = {
      kind: "open_azure_resource",
      href: `https://portal.azure.com/#@tenant.example/resource${VM_ID}/overview`,
      resourceId: VM_ID,
      evidenceId: "resource-1",
    };

    expect(safeDefenderPortalHref(action, [VM_ID])).toBe(action.href);
    expect(safeDefenderPortalHref(action, [])).toBeNull();
    expect(safeDefenderPortalHref(action, [REGISTRY_ID])).toBeNull();
    expect(
      safeDefenderPortalHref(
        { ...action, href: `https://portal.azure.com/#resource${REGISTRY_ID}/overview` },
        [VM_ID, REGISTRY_ID],
      ),
    ).toBeNull();
  });

  it("binds registry and cluster actions to their exact resource provider type", () => {
    expect(safeDefenderPortalHref(actions[4], [REGISTRY_ID])).toBe(actions[4].href);
    expect(safeDefenderPortalHref(actions[5], [CLUSTER_ID])).toBe(actions[5].href);
    expect(
      safeDefenderPortalHref(
        { ...actions[4], resourceId: CLUSTER_ID, href: actions[5].href },
        [CLUSTER_ID],
      ),
    ).toBeNull();
    expect(
      safeDefenderPortalHref(
        { ...actions[5], resourceId: REGISTRY_ID, href: actions[4].href },
        [REGISTRY_ID],
      ),
    ).toBeNull();
  });

  it("renders missing and unsafe destinations as disabled guidance rather than links", () => {
    render(
      <DefenderHandoff
        actions={[
          {
            kind: "open_defender_alert",
            href: "",
            evidenceId: "alert-missing",
            disabledReason: "Defender did not provide an alert destination.",
          },
          {
            kind: "open_defender_recommendation",
            href: "https://evil.example/recommendation",
            evidenceId: "recommendation-unsafe",
          },
        ]}
      />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText("Defender did not provide an alert destination."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No safe Azure portal destination was provided. Review the evidence in Exposure.",
      ),
    ).toBeInTheDocument();
    for (const label of [
      "Open alert in Defender for Cloud",
      "Open recommendation in Defender for Cloud",
    ]) {
      expect(screen.getByText(label).closest("[aria-disabled='true']")).not.toBeNull();
    }
  });

  it("keeps governed remediation separate and makes container handoffs review-only", () => {
    render(
      <DefenderHandoff
        actions={[]}
        governedHandoff={{
          outcome: "review_handoff",
          href: "/remediation?handoff=container-review-1",
          representedTargets: 1,
          totalTargets: 2,
          excludedReasons: ["One workload has unknown digest evidence"],
        }}
      />,
    );

    const region = screen.getByRole("group", { name: "Governed remediation handoff" });
    expect(
      within(region).getByRole("link", { name: "Open governed remediation" }),
    ).toHaveAttribute("href", "/remediation?handoff=container-review-1");
    expect(region).toHaveTextContent(
      "Review only. Nothing executes from Exposure.",
    );
    expect(region).toHaveTextContent(
      "Handoff available for 1 of 2 represented targets.",
    );
    expect(region).toHaveTextContent("One workload has unknown digest evidence");
  });

  it("renders no-safe-action container guidance without a remediation link", () => {
    render(
      <DefenderHandoff
        actions={[]}
        governedHandoff={{
          outcome: "no_safe_action",
          reason:
            "No safe review handoff is available until exact digest evidence is observed.",
        }}
      />,
    );

    const region = screen.getByRole("group", { name: "Governed remediation handoff" });
    expect(region).toHaveTextContent("No safe action");
    expect(region).toHaveTextContent(
      "No safe review handoff is available until exact digest evidence is observed.",
    );
    expect(within(region).queryByRole("link")).not.toBeInTheDocument();
  });

  it("rejects a governed handoff that is not a same-origin remediation path", () => {
    render(
      <DefenderHandoff
        actions={[]}
        governedHandoff={{
          outcome: "eligible",
          href: "https://evil.example/remediation",
          reason: "Return to Exposure and retry the governed handoff.",
        }}
      />,
    );

    expect(screen.queryByRole("link", { name: "Open governed remediation" })).not.toBeInTheDocument();
    expect(
      screen.getByText("Return to Exposure and retry the governed handoff."),
    ).toBeInTheDocument();
  });
});
