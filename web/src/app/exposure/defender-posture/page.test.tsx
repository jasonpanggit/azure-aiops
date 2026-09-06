import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  exposureOverview: vi.fn(),
  defenderOverview: vi.fn(),
  defenderAlerts: vi.fn(),
  defenderAttackPaths: vi.fn(),
  defenderSecureScore: vi.fn(),
  defenderSecureScoreControls: vi.fn(),
  defenderPosture: vi.fn(),
  containerImageExposures: vi.fn(),
  executeContainerAction: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () =>
    new URLSearchParams(
      "subscription=sub-1&page_size=50&sort_by=priority_score&sort_direction=desc",
    ),
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: { subscription: ["sub-1"] } }),
}));

vi.mock("@/lib/services", () => ({
  vulnerabilityApi: api,
}));

import DefenderPosturePage from "./page";

const VM_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1";
const REGISTRY_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/acr-1";
const CLUSTER_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-1";

const portal = {
  alert:
    "https://portal.azure.com/#view/Microsoft_Azure_Security/AlertBlade/alertId/alert-1",
  attackPath:
    "https://portal.azure.com/#view/Microsoft_Azure_Security/AttackPathBlade/attackPathId/path-1",
  recommendation:
    "https://portal.azure.com/#view/Microsoft_Azure_Security/RecommendationBlade/assessmentKey/assessment-1",
  vm: `https://portal.azure.com/#resource${VM_ID}/overview`,
  registry: `https://portal.azure.com/#resource${REGISTRY_ID}/overview`,
  cluster: `https://portal.azure.com/#resource${CLUSTER_ID}/overview`,
};

function contract() {
  return {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-defender-1",
      filters: [
        {
          field: "source_family",
          operator: "eq",
          value: "defender",
        },
      ],
      sort: { field: "priority_score", direction: "desc" },
      target_kind: "all",
    },
    counts: {
      unit: "findings",
      returned: 5,
      represented: 5,
      total: 7,
      excluded: 2,
    },
    units: {
      finding_count: "count",
      secure_score: "percent",
    },
    completeness: {
      state: "partial",
      represented: 5,
      expected: 7,
      total: 7,
      excluded: 2,
      represented_connections: 1,
      expected_connections: 2,
      excluded_reasons: ["Defender West connection unavailable"],
    },
    freshness: {
      state: "current",
      as_of: "2026-09-06T08:00:00Z",
      source_family: "defender",
      threshold_seconds: 3600,
    },
    evidence_refs: [
      {
        source_family: "defender",
        source_id: "defender-evidence-1",
      },
    ],
    deep_link_action: {
      action_id: "open_exposure_detail",
      kind: "deep_link",
      path_field: "detail_path",
      fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
    },
    safe_error: null,
  };
}

function commonEnvelope() {
  const commonContract = contract();
  return {
    data: {
      total_count: 7,
      generation: "generation-defender-1",
      applied: {
        scope: { subscription: ["sub-1"] },
        filters: commonContract.query.filters,
        sort: commonContract.query.sort,
      },
      completeness: commonContract.completeness,
      freshness: commonContract.freshness,
      contract: commonContract,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-defender-1",
    pagination: null,
  };
}

function envelope<T>(data: T) {
  return {
    data,
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-defender-1",
  };
}

const alert = {
  id: "alert-1",
  title: "Credential theft detected",
  description: "Suspicious token activity",
  status: "Active",
  severity: "High",
  intent: "CredentialAccess",
  productName: "Defender for Cloud",
  timeGenerated: "2026-09-06T07:00:00Z",
  remediationSteps: ["Rotate the credential"],
  resourceIds: [VM_ID],
  subscription_id: "sub-1",
  portal_actions: [
    {
      kind: "open_defender_alert",
      href: portal.alert,
      evidenceId: "alert-1",
    },
    {
      kind: "open_azure_resource",
      href: portal.vm,
      resourceId: VM_ID,
      evidenceId: "resource-evidence-1",
    },
  ],
  governed_handoff: {
    outcome: "eligible",
    href: "/remediation?handoff=alert-1",
    representedTargets: 1,
    totalTargets: 1,
  },
};

const attackPath = {
  id: "path-1",
  title: "Internet to production VM",
  description: "A privileged route reaches vm-1",
  potentialImpact: "Subscription compromise",
  riskCategories: ["Privilege escalation"],
  manualRemediationSteps: ["Review the exposed identity"],
  nodeCount: 1,
  connectionCount: 0,
  nodes: [
    {
      id: "node-1",
      displayName: "vm-1",
      nodeType: "microsoft.compute/virtualmachines",
      resourceId: VM_ID,
      resolved: true,
      portal_actions: [
        {
          kind: "open_azure_resource",
          href: portal.vm,
          resourceId: VM_ID,
          evidenceId: "path-node-1",
        },
      ],
    },
  ],
  connections: [],
  subscription_id: "sub-1",
  portal_actions: [
    {
      kind: "open_defender_attack_path",
      href: portal.attackPath,
      evidenceId: "path-1",
    },
  ],
  governed_handoff: {
    outcome: "eligible",
    href: "/remediation?handoff=path-1",
    representedTargets: 1,
    totalTargets: 2,
    excludedReasons: ["One path node is outside the authorized scope"],
  },
};

const recommendation = {
  assessment_id: "assessment-1",
  asset_id: VM_ID,
  asset_name: "vm-1",
  resource_type: "microsoft.compute/virtualmachines",
  inventory_kind: "Azure VM",
  defender_plan: "Defender for Servers",
  status: "Unhealthy",
  severity: "High",
  recommendation: "Enable endpoint protection",
  description: "Endpoint protection is missing",
  remediation: "Review the Defender recommendation",
  last_assessed_at: "2026-09-06T06:00:00Z",
  subscription_id: "sub-1",
  portal_actions: [
    {
      kind: "open_defender_recommendation",
      href: portal.recommendation,
      evidenceId: "assessment-1",
    },
    {
      kind: "open_azure_resource",
      href: portal.vm,
      resourceId: VM_ID,
      evidenceId: "assessment-resource-1",
    },
  ],
  governed_handoff: {
    outcome: "eligible",
    href: "/remediation?handoff=assessment-1",
    representedTargets: 1,
    totalTargets: 1,
  },
};

const container = {
  id: "image-1",
  target_resource_id: "sha256:aaaaaaaa",
  registry_resource_id: REGISTRY_ID,
  registry_host: "acr-1.azurecr.io",
  repository: "platform/api",
  image_digest: "sha256:aaaaaaaa",
  image_tags: ["1.0.0"],
  image_uri: "acr-1.azurecr.io/platform/api@sha256:aaaaaaaa",
  last_pushed_at: "2026-09-05T00:00:00Z",
  status: "Active",
  severity: "Critical",
  critical_count: 1,
  high_count: 2,
  vulnerable_package_count: 3,
  cve_count: 1,
  cve_ids: ["CVE-2026-2001"],
  vulnerable_packages: ["openssl"],
  recommendation: "Review image exposure",
  last_assessed_at: "2026-09-06T06:00:00Z",
  subscription_id: "sub-1",
  observed_cluster_ids: [CLUSTER_ID],
  represented_workload_count: 1,
  total_workload_count: 3,
  unknown_workload_count: 2,
  portal_actions: [
    {
      kind: "open_registry",
      href: portal.registry,
      resourceId: REGISTRY_ID,
      evidenceId: "registry-evidence-1",
    },
    {
      kind: "open_cluster",
      href: portal.cluster,
      resourceId: CLUSTER_ID,
      evidenceId: "cluster-evidence-1",
    },
  ],
  governed_handoff: {
    outcome: "review_handoff",
    href: "/remediation?handoff=image-1",
    representedTargets: 1,
    totalTargets: 3,
    excludedReasons: ["Two workloads have unknown digest evidence"],
  },
};

describe("DefenderPosturePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.exposureOverview.mockResolvedValue(commonEnvelope());
    api.defenderOverview.mockResolvedValue(
      envelope({
        active_alert_count: 1,
        critical_alert_count: 0,
        attack_path_count: 1,
        unhealthy_recommendation_count: 1,
        vulnerable_container_image_count: 1,
        container_image_cve_count: 1,
        secure_scores: [],
        top_controls: [],
        coverage: {},
      }),
    );
    api.defenderAlerts.mockResolvedValue(envelope([alert]));
    api.defenderAttackPaths.mockResolvedValue(envelope([attackPath]));
    api.defenderSecureScore.mockResolvedValue(
      envelope([
        {
          id: "score-sub-1",
          subscription_id: "sub-1",
          currentScore: 10,
          maxScore: 20,
          percentage: 50,
          observedAt: "2026-09-06T08:00:00Z",
        },
        {
          id: "score-sub-2",
          subscription_id: "sub-2",
          currentScore: 9,
          maxScore: 80,
          percentage: 11.25,
          observedAt: "2026-09-06T08:00:00Z",
        },
      ]),
    );
    api.defenderSecureScoreControls.mockResolvedValue(
      envelope([
        {
          id: "control-1",
          title: "Protect management ports",
          currentScore: 2,
          maxScore: 8,
          percentage: 0.25,
          unhealthyResourceCount: 2,
          healthyResourceCount: 1,
          assessmentDefinitions: [],
          subscription_id: "sub-1",
        },
      ]),
    );
    api.defenderPosture.mockResolvedValue(envelope([recommendation]));
    api.containerImageExposures.mockResolvedValue(envelope([container]));
  });

  it("renders independently governed Defender sections with exact handoffs and conservative coverage", async () => {
    render(<DefenderPosturePage />);

    expect(
      await screen.findByRole("heading", { name: "Credential theft detected" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Internet to production VM" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Enable endpoint protection" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /platform\/api:1.0.0/ })).toBeInTheDocument();

    expect(screen.getByLabelText("Secure score — all authorized subscriptions value")).toHaveTextContent(
      "19.0%",
    );
    expect(
      screen.getByText("19 of 100 points across 2 authorized subscriptions"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 / 8 points · 25.0%")).toBeInTheDocument();

    for (const label of [
      "Open alert in Defender for Cloud",
      "Open attack path in Defender for Cloud",
      "Open recommendation in Defender for Cloud",
      "Open affected resource in Azure portal",
      "Open registry in Azure portal",
      "Open cluster in Azure portal",
    ]) {
      expect(
        screen.getAllByRole("link", {
          name: `${label} (opens Azure portal in a new tab)`,
        }).length,
      ).toBeGreaterThan(0);
    }

    expect(
      screen.getByRole("status", { name: "Defender posture evidence status" }),
    ).toHaveTextContent("Partial operational context");
    expect(screen.getAllByText("Defender West connection unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/This is not a full blast radius/)).toBeInTheDocument();
    expect(screen.getByText("Review only. Nothing executes from Exposure.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rebuild|deploy|mutate/i })).not.toBeInTheDocument();
    expect(api.executeContainerAction).not.toHaveBeenCalled();

    expect(api.exposureOverview).toHaveBeenCalled();
    const queryState = api.exposureOverview.mock.calls[0][0];
    expect(queryState.scope).toEqual({ subscription: ["sub-1"] });
    expect(queryState.filters.source_family).toBe("defender");
  });

  it("keeps sibling sections usable when alerts fail and retries only alerts with focus retained", async () => {
    api.defenderAlerts
      .mockRejectedValueOnce(new Error("Alerts provider unavailable"))
      .mockResolvedValueOnce(envelope([alert]));

    render(<DefenderPosturePage />);

    expect(
      await screen.findByText("Defender alerts is unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText("Internet to production VM")).toBeInTheDocument();
    expect(screen.getByText("Enable endpoint protection")).toBeInTheDocument();

    const retry = screen.getByRole("button", { name: "Retry Defender alerts" });
    retry.focus();
    fireEvent.click(retry);
    expect(document.activeElement).toBe(retry);

    expect(
      await screen.findByRole("heading", { name: "Credential theft detected" }),
    ).toBeInTheDocument();
    expect(api.defenderAlerts).toHaveBeenCalledTimes(2);
    expect(api.defenderAttackPaths).toHaveBeenCalledTimes(1);
  });

  it("disables unsafe or missing portal destinations without hiding valid rows", async () => {
    api.defenderAlerts.mockResolvedValue(
      envelope([
        {
          ...alert,
          portal_actions: [
            {
              kind: "open_defender_alert",
              href: "https://portal.azure.com.evil.example/#view/Microsoft_Azure_Security/AlertBlade/alertId/alert-1",
              evidenceId: "alert-1",
            },
          ],
        },
      ]),
    );
    api.defenderPosture.mockResolvedValue(
      envelope([{ ...recommendation, portal_actions: [] }]),
    );

    render(<DefenderPosturePage />);

    expect(
      await screen.findByRole("heading", { name: "Credential theft detected" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", {
        name: "Open alert in Defender for Cloud (opens Azure portal in a new tab)",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Open alert in Defender for Cloud")[0]).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getAllByText("Open recommendation in Defender for Cloud")[0]).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(
      screen.getAllByText(
        "No safe Azure portal destination was provided. Review the evidence in Exposure.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("gives keyboard focus to precise links and exposes no server action for mixed assets", async () => {
    api.defenderPosture.mockResolvedValue(
      envelope([
        {
          ...recommendation,
          assessment_id: "assessment-mixed",
          asset_id: "mixed:server-and-image",
          asset_name: "vm-1 and platform/api",
          resource_type: "mixed",
          inventory_kind: "Server + container image",
          portal_actions: [
            {
              kind: "open_defender_recommendation",
              href: portal.recommendation,
              evidenceId: "assessment-mixed",
            },
          ],
          governed_handoff: {
            outcome: "no_safe_action",
            reason: "Mixed targets require separate evidence review.",
          },
        },
      ]),
    );

    render(<DefenderPosturePage />);

    const recommendationLink = await screen.findByRole("link", {
      name: "Open recommendation in Defender for Cloud (opens Azure portal in a new tab)",
    });
    recommendationLink.focus();
    expect(document.activeElement).toBe(recommendationLink);
    expect(screen.getByText("Mixed asset")).toBeInTheDocument();
    const handoff = screen.getByRole("group", {
      name: "Governed remediation handoff",
    });
    expect(within(handoff).getByText("No safe action")).toBeInTheDocument();
    expect(within(handoff).queryByRole("link")).not.toBeInTheDocument();
  });
});
