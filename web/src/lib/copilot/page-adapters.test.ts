import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { CopilotPageKind, CopilotPageKindV2, CopilotPageSnapshot } from "@/lib/types";
import { buildTopologyEnvelope } from "@/test/network-fixtures";
import {
  buildChangesCopilotContext,
  buildComplianceCopilotContext,
  buildConnectionsCopilotContext,
  buildCveDetailCopilotContext,
  buildDefenderPostureCopilotContext,
  buildExposureCopilotContext,
  buildFabricMedallionCopilotContext,
  buildFinOpsCopilotContext,
  buildGovernanceCopilotContext,
  buildIdentityCopilotContext,
  buildInventoryCopilotContext,
  buildInvestigationCopilotContext,
  buildKbDetailCopilotContext,
  buildNetworkCopilotContext,
  buildOverviewCopilotContext,
  buildPatchPrioritiesCopilotContext,
  buildPredeployCopilotContext,
  buildRemediationCopilotContext,
  buildResourceHealthCopilotContext,
  buildServiceDetailCopilotContext,
  buildServicesCopilotContext,
  buildSituationDetailCopilotContext,
  buildSituationsCopilotContext,
  buildTwinCopilotContext,
  canonicalEvidenceStableId,
  CORE_COPILOT_PAGE_ADAPTERS,
  COPILOT_ROUTE_DISPOSITIONS,
  COPILOT_ROUTE_STARTER_HINTS,
  COPILOT_SNAPSHOT_LIMITS,
  copilotPageDisposition,
  normalizeCopilotSnapshotV2,
  serializeCopilotSnapshot,
  type InventoryCopilotRecord,
} from "./page-adapters";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

function expectCanonicalEndpointAccepts(
  requests: Array<{
    name: string;
    requested_scope: Record<string, string[]>;
    snapshot: ReturnType<typeof normalizeCopilotSnapshotV2>;
    semantic_available: boolean;
    expected_claim_types?: string[];
  }>,
) {
  const validator = `
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context

from api.app import create_app
from operations.orchestration_contract import OrchestrationResult
from semantic.semantic_engine import SemanticEngine
from semantic.semantic_indexes import SemanticIndexes

requests = json.load(sys.stdin)
observed = []
engine = SemanticEngine(
    SemanticIndexes(
        [
            {
                "resource_id": f"{namespace}-visible-1",
                "entity_type": entity_type,
                "name": f"{namespace}-visible-1",
                "subscription_id": "sub-a",
                "lifecycle_status": "active",
            }
            for namespace, entity_type in (
                ("overview", "ExecutiveSummary"),
                ("governance", "GovernanceRole"),
                ("identity", "Principal"),
                ("finops", "CostAttribution"),
            )
        ],
        [],
    ),
    knowledge_version="page-adapter-regression",
    freshness="2026-09-13T00:00:00Z",
)

def execute(_self, request, **kwargs):
    selection = kwargs["selection_snapshot"]
    canonical = kwargs["canonical_selection_snapshot"]
    assert request.requested_scope == {"subscription": ["sub-a"]}
    assert selection.material_claims
    evidence_ids = {row.evidence_id for row in selection.evidence}
    assert all(
        set(claim.evidence_refs) <= evidence_ids
        for claim in selection.material_claims
    )
    retained_refs = {
        ref
        for row in canonical.evidence
        for ref in row.evidence_refs
    }
    assert {
        ref
        for claim in selection.material_claims
        for ref in claim.evidence_refs
    } <= retained_refs
    retained_claim_types = {row.claim_type for row in canonical.evidence}
    assert set(item.get("expected_claim_types") or []) <= retained_claim_types
    return OrchestrationResult(
        status="ok",
        policy_status="accepted",
        coverage=selection.coverage,
        thread_id="thr-" + ("a" * 32),
        thread_revision=1,
    )

with tempfile.TemporaryDirectory() as directory:
    with patch("api.routers.copilot.OrchestrationService.execute", execute):
        for item in requests:
            client = TestClient(
                create_app(
                    _context(
                        Path(directory),
                        None,
                        engine=engine if item["semantic_available"] else None,
                    )
                ),
                raise_server_exceptions=False,
            )
            response = client.post(
                "/api/v1/copilot/investigations?subscription=sub-a",
                headers=HEADERS,
                json={
                    "contract_version": "1",
                    "question": "Explain the visible page state.",
                    "requested_scope": item["requested_scope"],
                    "snapshot": item["snapshot"],
                },
            )
            observed.append({
                "name": item["name"],
                "status": response.status_code,
                "body": response.text if response.status_code != 200 else "",
            })

print(json.dumps(observed, sort_keys=True))
`;
  const result = spawnSync("python3", ["-c", validator], {
    cwd: REPO_ROOT,
    encoding: "utf8",
    input: JSON.stringify(requests),
  });

  expect(result.status, result.stderr || result.stdout).toBe(0);
  expect(JSON.parse(result.stdout)).toEqual(
    requests.map(({ name }) => ({ name, status: 200, body: "" })),
  );
}

const records: InventoryCopilotRecord[] = [
  {
    identity: "Windows Server|2019",
    kind: "os_group",
    source: "inventory/os_observations",
    observedAt: "2026-08-25T10:00:00Z",
    data: {
      os_name: "Windows Server",
      os_version: "2019",
      machine_count: 2,
    },
  },
  {
    identity: "vm-1",
    kind: "azure_group",
    source: "inventory/resource_observations",
    observedAt: "2026-08-25T10:00:00Z",
    resourceId:
      "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.App/containerApps/App-1",
    data: {
      resource_type: "microsoft.app/containerapps",
      resource_count: 1,
    },
  },
];

const baseInput = {
  scope: { subscription: ["sub-a"] },
  tab: "os" as const,
  filters: { search: "windows", lifecycle: "supported" },
  sort: { os_name: "asc" as const },
  records,
  selectedIdentity: "Windows Server|2019",
  totalCount: 4,
  offset: 0,
  limit: 50,
  sourceStatuses: [
    {
      source: "azure_vm",
      observedAt: "2026-08-25T10:00:00Z",
      status: "fresh",
    },
    {
      source: "arc",
      observedAt: "2026-08-25T09:00:00Z",
      status: "partial",
    },
  ],
};

describe("Copilot starter hint backend parity", () => {
  it("validates every emitted integrated hint against the backend schema", () => {
    const hints = Object.entries(COPILOT_ROUTE_STARTER_HINTS).flatMap(
      ([route, starters]) => starters.map((starter) => ({
        route,
        label: starter.label,
        specialist_id: starter.specialistId,
        tool: starter.tool,
        arguments: starter.toolArguments ?? {},
      })),
    );
    const validator = `
import json
import sys

sys.path.insert(0, "src")
from operations.mcp_server import reviewed_tools_for_specialist, validate_tool_arguments

errors = []
for hint in json.load(sys.stdin):
    tool = hint.get("tool")
    if not tool:
        continue
    specialist_id = hint.get("specialist_id") or ""
    if tool not in reviewed_tools_for_specialist(specialist_id):
        errors.append({**hint, "error": "tool is not granted to specialist"})
        continue
    try:
        validate_tool_arguments(tool, hint.get("arguments") or {})
    except ValueError as exc:
        errors.append({**hint, "error": str(exc)})
print(json.dumps(errors, sort_keys=True))
raise SystemExit(1 if errors else 0)
`;

    const result = spawnSync("python3", ["-c", validator], {
      cwd: REPO_ROOT,
      encoding: "utf8",
      input: JSON.stringify(hints),
    });

    expect(result.status, result.stderr || result.stdout).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual([]);
  });
});

describe("investigation Copilot adapter", () => {
  it("retains bounded observations and marks over-50 source coverage partial", () => {
    const context = buildInvestigationCopilotContext({
      scope: { subscription: ["sub-a"] },
      filters: { entry_type: ["BusinessService"], subject: ["Payments"] },
      records: Array.from({ length: 51 }, (_, index) => ({
        identity: `incident-${index}`,
        namespace: "operations",
        kind: "incident",
        source: "investigate/incidents",
        evidenceIdentity: "observation" as const,
        data: { title: `Incident ${index}`, severity: "high" },
      })),
      evidence: [],
      coverage: [{
        key: "incidents",
        visibleCount: 50,
        totalCount: 51,
        truncated: true,
        available: true,
      }],
      sourceStatuses: [{
        source: "incidents",
        observedAt: "2026-01-01T10:00:00Z",
        status: "fresh",
      }],
    });
    const snapshot = normalizeCopilotSnapshotV2(context.snapshot);

    expect(snapshot).toMatchObject({
      page_kind: "investigate",
      page_id: "investigate",
      coverage: { visible_count: 50, total_count: 51, complete: false },
    });
    expect(snapshot.selected_entities).toEqual([]);
    expect(snapshot.evidence.every((row) => row.actionable === false)).toBe(true);
    expect(snapshot.evidence.filter(
      (row) => row.source === "investigate/incidents",
    )).toHaveLength(50);
    expect(context.uncertainty).toContain("incidents coverage is truncated");
  });
});

describe("shared page adapter canonical endpoint compatibility", () => {
  it("posts representative Overview, Governance, Identity, FinOps, and Remediation snapshots", () => {
    const representativeInput = (
      namespace: string,
      kind: string,
      resourceId?: string,
    ) => ({
      scope: { subscription: ["sub-a"] },
      filters: { view: [namespace] },
      records: [
        {
          identity: `${namespace}-visible-1`,
          namespace,
          kind,
          source: `${namespace}/visible`,
          ...(resourceId ? { resourceId } : {}),
          observedAt: "2026-09-13T00:00:00Z",
          selected: true,
          data: { title: `${namespace} visible observation` },
        },
      ],
      evidence: [
        {
          source_engine: "PageAdapterRegression",
          source_table: `${namespace}_provenance`,
          timestamp: "2026-09-13T00:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
      coverage: [
        {
          key: `${namespace}_rows`,
          visibleCount: 1,
          totalCount: 2,
          truncated: true,
        },
      ],
      sourceStatuses: [
        {
          source: namespace,
          observedAt: "2026-09-13T00:00:00Z",
          status: "fresh" as const,
        },
      ],
    });
    const resourceId =
      "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1";
    const contexts = [
      {
        name: "Overview",
        semanticAvailable: true,
        context: buildOverviewCopilotContext(
          representativeInput("overview", "executive_summary"),
        ),
      },
      {
        name: "Governance",
        semanticAvailable: false,
        context: buildGovernanceCopilotContext({
          scope: { subscription: ["sub-a"] },
          roles: [
            { role_id: "operator", name: "Operator", permissions: ["read"] },
          ],
          rolesTotalCount: 1,
          policies: [{ section: "retention_policy", setting_count: 2 }],
          accessReviewAudiences: ["security"],
          auditExportKinds: ["identity"],
          settingsAvailable: true,
          audiencesAvailable: true,
          kindsAvailable: true,
          freshness: "fresh",
          observedAt: "2026-09-13T00:00:00Z",
          evidence: [],
        }),
      },
      {
        name: "Identity",
        semanticAvailable: true,
        context: buildIdentityCopilotContext(
          representativeInput("identity", "identity_principal"),
        ),
      },
      {
        name: "FinOps",
        semanticAvailable: true,
        context: buildFinOpsCopilotContext(
          representativeInput("finops", "cost_attribution"),
        ),
      },
      {
        name: "Remediation",
        semanticAvailable: true,
        context: buildRemediationCopilotContext(
          representativeInput("remediation", "remediation_plan", resourceId),
        ),
      },
    ];
    const requests = contexts.map(({ name, context, semanticAvailable }) => ({
      name,
      requested_scope: context.requestedScope,
      snapshot: normalizeCopilotSnapshotV2(context.snapshot),
      semantic_available: semanticAvailable,
    }));

    expectCanonicalEndpointAccepts(requests);
    const syntheticRows = requests
      .flatMap(({ snapshot }) => snapshot.evidence)
      .filter(({ claim_type }) =>
        claim_type === "coverage" || claim_type === "source_observation");
    expect(syntheticRows.length).toBeGreaterThan(0);
    expect(syntheticRows.every(({ entity }) => entity.type === "observation")).toBe(true);
  });
});

describe("inventory Copilot page adapter", () => {
  it("has an explicit integrated route disposition", () => {
    expect(copilotPageDisposition("/inventory")).toBe("integrated");
  });

  describe("Network topology selection adapter", () => {
    const hubId =
      "/subscriptions/sub-a/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/hub-vnet";
    const spokeId =
      "/subscriptions/sub-a/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/spoke-vnet";

    function networkInput() {
      const topology = buildTopologyEnvelope();
      topology.data.topology.resources = [
        {
          id: hubId,
          name: "hub-vnet",
          entity_type: "VNet",
          role: "hub",
          subscription_id: "sub-a",
          resource_group: "rg-network",
          location: "eastus",
          connection_id: "conn-a",
          environment: "prod",
          business_service: "",
          application: "",
          owner: "",
          tags: {},
          details: { peer_count: 1 },
        },
        {
          id: spokeId,
          name: "spoke-vnet",
          entity_type: "VNet",
          role: "spoke",
          subscription_id: "sub-a",
          resource_group: "rg-network",
          location: "eastus",
          connection_id: "conn-a",
          environment: "prod",
          business_service: "",
          application: "",
          owner: "",
          tags: {},
          details: { peer_count: 1 },
        },
      ];
      topology.data.topology.relationships = [{
        id: "hub-to-spoke",
        source: hubId,
        target: spokeId,
        relationship_type: "peered_to",
        label: "peered to",
        details: {},
      }];
      return {
        scope: { subscription: ["sub-a"] },
        tab: "topology" as const,
        gapOffset: 0,
        gapLimit: 20,
        findingOffset: 0,
        findingLimit: 20,
        topology,
      };
    }

    it("does not select every hub when the graph has no selection", () => {
      const context = buildNetworkCopilotContext(networkInput());

      expect(context.snapshot.selected_resources).toEqual([]);
      expect(context.selectedEntities).toEqual([]);
      expect(context.snapshot.evidence.every((row) => row.data.selected !== true)).toBe(true);
    });

    it("canonicalizes a selected VNet as the only selected resource and first starter", () => {
      const context = buildNetworkCopilotContext({
        ...networkInput(),
        selection: {
          node: {
            id: hubId,
            label: "hub-vnet",
            kind: "hub",
            entityType: "VNet",
          },
          edge: null,
        },
      });

      expect(context.snapshot.selected_resources).toEqual([{
        resource_id: hubId.toLowerCase(),
        resource_type: "Microsoft.Network/virtualNetworks",
        name: "hub-vnet",
      }]);
      expect(context.selectedEntities).toEqual([{
        type: "azure",
        resource_id: hubId.toLowerCase(),
      }]);
      expect(
        context.snapshot.evidence.filter((row) => row.data.selected === true),
      ).toHaveLength(1);
      expect(context.starterQuestions[0]).toMatchObject({
        label: "Explain hub-vnet (hub).",
        specialistId: "network",
        tool: "network_topology",
        toolArguments: { selector: hubId },
      });
      expect(context.starterQuestions.slice(1).map((starter) => starter.label)).toEqual([
        "Can UAT reach PROD?",
        "Show inspection bypass paths.",
      ]);
    });

    it("selects only a relationship and its canonical endpoints within the adjacency bound", () => {
      const context = buildNetworkCopilotContext({
        ...networkInput(),
        selection: {
          node: null,
          edge: {
            id: "hub-to-spoke",
            source: hubId,
            target: spokeId,
            label: "peered to",
            kind: "relationship",
            relationshipType: "peered_to",
          },
        },
      });

      expect(context.snapshot.selected_resources).toEqual([
        expect.objectContaining({ resource_id: hubId.toLowerCase() }),
        expect.objectContaining({ resource_id: spokeId.toLowerCase() }),
      ]);
      expect(
        context.snapshot.evidence.filter((row) => row.data.selected === true),
      ).toHaveLength(3);
      expect(
        context.snapshot.evidence.filter((row) => row.data.relationship_type),
      ).toHaveLength(1);
    });
  });

  const corePageInput = {
    scope: { subscription: ["sub-a"] },
    filters: { search: ["critical"] },
    sort: { priority: "asc" as const },
    records: [
      {
        identity: "situation-1",
        namespace: "operations",
        kind: "situation",
        source: "situations/visible",
        observedAt: "2026-09-07T10:00:00Z",
        selected: true,
        data: { title: "Critical service interruption", priority: "P1" },
      },
      {
        identity:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/Hub-1",
        namespace: "network",
        kind: "virtual_network",
        source: "network/topology",
        resourceId:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/Hub-1",
        resourceType: "Microsoft.Network/virtualNetworks",
        name: "Hub-1",
        observedAt: "2026-09-07T09:00:00Z",
        selected: true,
        data: { role: "hub" },
      },
    ],
    evidence: [
      {
        source_engine: "ARG",
        source_table: "resources",
        timestamp: "2026-09-07T10:00:00Z",
        resource_id:
          "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/hub-1",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
    coverage: [
      {
        key: "situations",
        visibleCount: 2,
        totalCount: 5,
        truncated: true,
      },
    ],
    sourceStatuses: [
      {
        source: "situations",
        observedAt: "2026-09-07T10:00:00Z",
        status: "fresh" as const,
      },
      {
        source: "network",
        observedAt: "2026-09-07T09:00:00Z",
        status: "partial" as const,
      },
    ],
  };

  describe("core Copilot page adapters", () => {
    it("registers Overview, Network, Compliance, Exposure, Situations, and Remediation as integrated routes", () => {
      expect(Object.keys(CORE_COPILOT_PAGE_ADAPTERS)).toEqual([
        "/",
        "/compliance",
        "/exposure",
        "/network",
        "/remediation",
        "/situations",
      ]);
      expect(copilotPageDisposition("/")).toBe("integrated");
      expect(copilotPageDisposition("/network")).toBe("integrated");
      expect(copilotPageDisposition("/compliance")).toBe("integrated");
      expect(copilotPageDisposition("/exposure")).toBe("integrated");
      expect(copilotPageDisposition("/situations")).toBe("integrated");
      expect(copilotPageDisposition("/remediation")).toBe("integrated");
    });

    it("builds bounded Overview evidence with stable domain identities and conditional executive intent", () => {
      const context = buildOverviewCopilotContext(corePageInput);
      const reordered = buildOverviewCopilotContext({
        ...corePageInput,
        records: [...corePageInput.records].reverse().map((record) => ({
          ...record,
          observedAt: "2026-09-08T10:00:00Z",
        })),
      });

      expect(context.snapshot).toMatchObject({
        version: "1",
        page_kind: "resource",
        page_id: "operations-overview",
        filters: {
          search: ["critical"],
          sort: ["priority:asc"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "operations",
          kind: "situation",
          source_key: "situation-1",
        },
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/hub-1",
        },
      ]);
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.snapshot.evidence).toHaveLength(
        Math.min(context.snapshot.evidence.length, COPILOT_SNAPSHOT_LIMITS.evidenceRows),
      );
      expect(context.starterQuestions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            specialistId: "incident",
            tool: "incidents",
          }),
          expect.objectContaining({
            specialistId: "executive_summary",
          }),
        ]),
      );
      expect(
        context.starterQuestions.find(
          (starter) => starter.specialistId === "executive_summary",
        ),
      ).not.toHaveProperty("tool");
      expect(
        context.starterQuestions.filter(
          (starter) => starter.specialistId === "executive_summary",
        ),
      ).toHaveLength(1);
    });

    it("preserves Network selection, tab filters, pagination coverage, freshness, and read-only hints", () => {
      const context = buildNetworkCopilotContext({
        ...corePageInput,
        filters: { tab: ["gaps"] },
        sort: { severity: "desc" },
        coverage: [
          {
            key: "gaps",
            visibleCount: 100,
            totalCount: 340,
            truncated: true,
          },
          {
            key: "rule_findings",
            visibleCount: 100,
            totalCount: 620,
            truncated: true,
          },
        ],
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "network",
        page_id: "network-topology",
        filters: {
          tab: ["gaps"],
          sort: ["severity:desc"],
        },
        selected_resources: [
          {
            resource_id:
              "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/hub-1",
            resource_type: "Microsoft.Network/virtualNetworks",
            name: "Hub-1",
          },
        ],
        freshness: [
          {
            source: "network",
            observed_at: "2026-09-07T09:00:00Z",
            status: "partial",
          },
          {
            source: "situations",
            observed_at: "2026-09-07T10:00:00Z",
            status: "fresh",
          },
        ],
      });
      expect(context.coverage).toEqual({
        gaps: {
          visible_count: 100,
          total_count: 340,
          complete: false,
          truncated: true,
        },
        rule_findings: {
          visible_count: 100,
          total_count: 620,
          complete: false,
          truncated: true,
        },
      });
      expect(context.uncertainty).toEqual([
        "gaps coverage is truncated",
        "rule_findings coverage is truncated",
        "network freshness is partial",
      ]);
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "network"
        && !/write|update|delete|execute/i.test(starter.tool ?? ""),
      )).toBe(true);
    });

    it("preserves Compliance policy/resource evidence, aggregate coverage, selection, and governance hints", () => {
      const context = buildComplianceCopilotContext({
        ...corePageInput,
        filters: {
          policy: ["Approved landing zone"],
          selected: ["policy-1"],
        },
        sort: { severity: "desc" },
        records: [
          {
            identity: "policy-1",
            namespace: "compliance",
            kind: "policy_violation",
            source: "compliance/violations",
            selected: true,
            observedAt: "2026-09-07T10:00:00Z",
            data: {
              policy: "Approved landing zone",
              resource: "payroll-sql",
              severity: "critical",
            },
          },
          {
            identity: "deviation-1",
            namespace: "compliance",
            kind: "governed_deviation",
            source: "compliance/deviations",
            observedAt: "2026-09-07T09:00:00Z",
            data: {
              control: "private-access",
              resource: "payroll-sql",
              status: "open",
            },
          },
        ],
        coverage: [
          {
            key: "violations",
            visibleCount: 2,
            totalCount: 7,
            truncated: true,
          },
        ],
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "governance",
        page_id: "compliance-posture",
        filters: {
          policy: ["Approved landing zone"],
          selected: ["policy-1"],
          sort: ["severity:desc"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "compliance",
          kind: "policy_violation",
          source_key: "policy-1",
        },
      ]);
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "compliance",
                kind: "policy_violation",
                source_key: "policy-1",
              },
              mutation_authorized: false,
              selected: true,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              coverage: {
                visible_count: 2,
                total_count: 7,
                complete: false,
                truncated: true,
              },
            }),
          }),
        ]),
      );
      expect(context.starterQuestions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            specialistId: "governance",
          }),
          expect.objectContaining({
            specialistId: "network",
            tool: "firewall_nsg_gaps",
            toolArguments: { category: "firewall_bypass" },
          }),
        ]),
      );
      expect(
        context.starterQuestions.find(
          (starter) => starter.specialistId === "governance",
        )?.tool,
      ).toBeUndefined();
    });

    it("never marks stale, partial, or unavailable observations as actionable", () => {
      const context = buildComplianceCopilotContext({
        ...corePageInput,
        records: corePageInput.records.map((record) => ({
          ...record,
          data: { ...record.data, actionable: true },
        })),
        sourceStatuses: corePageInput.sourceStatuses.map((source) => ({
          ...source,
          status: "stale" as const,
        })),
      });

      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false
        && row.data.mutation_authorized === false,
      )).toBe(true);
    });

    it("projects long Compliance identities into stable bounded keys without losing selection", () => {
      const longIdentity = `peering:${"remote-vnet/".repeat(16)}`;
      const input = {
        scope: {},
        policyName: "Approved landing zone",
        selectedId: longIdentity,
        violations: [{
          id: longIdentity,
          type: "peering",
          severity: "high",
          title: "Unapproved peering",
          detail: "The peering bypasses the approved hub.",
          resource: "hub-vnet",
          application: "Payments",
          businessService: "Checkout",
          owner: "Network",
          affectedTraffic: "Spoke to spoke",
          vulnerabilityExposure: "Unknown",
          remediation: "Route through the approved hub.",
        }],
        governedDeviations: [],
        evidence: [],
        sourceEnvelopes: {},
      };

      const context = buildComplianceCopilotContext(input);
      const repeated = buildComplianceCopilotContext(input);
      const selected = context.selectedEntities[0];

      expect(selected).toMatchObject({
        type: "domain",
        namespace: "compliance",
        kind: "policy_violation",
      });
      expect(selected?.type === "domain" ? selected.source_key.length : 0).toBeLessThanOrEqual(256);
      expect(context.snapshot.filters.selected).toEqual([
        selected?.type === "domain" ? selected.source_key : "",
      ]);
      expect(context.selectedEntities).toEqual(repeated.selectedEntities);
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({ selected: true }),
          }),
        ]),
      );
    });

    it("retains the latest evidence timestamp when live observation metadata is absent", () => {
      const context = buildOverviewCopilotContext({
        scope: {},
        situations: {
          data: [],
          evidence: [
            {
              source_engine: "ARG",
              source_table: "resources",
              timestamp: "2026-09-07T10:00:00Z",
              confidence: "high",
              freshness: "fresh",
            },
            {
              source_engine: "ARG",
              source_table: "resources",
              timestamp: "2026-09-07T11:00:00Z",
              confidence: "high",
              freshness: "fresh",
            },
          ],
          scope: {},
        },
        network: null,
        vulnerabilities: null,
        connections: null,
      });

      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          {
            source: "situations",
            observed_at: "2026-09-07T11:00:00Z",
            status: "fresh",
          },
        ]),
      );
    });

    it("derives deterministic domain identities when loaded rows omit their IDs", () => {
      const input = {
        ...corePageInput,
        records: [{
          identity: " ",
          namespace: "network",
          kind: "network_gap",
          source: "network/gaps",
          selected: true,
          data: {
            title: "Missing route",
            resource: "hub-vnet",
          },
        }],
        evidence: [],
      };

      const context = buildNetworkCopilotContext(input);
      const repeated = buildNetworkCopilotContext(input);
      const selected = context.selectedEntities[0];

      expect(selected).toMatchObject({
        type: "domain",
        namespace: "network",
        kind: "network_gap",
      });
      expect(selected?.type === "domain" ? selected.source_key : "").toMatch(/^anonymous:/);
      expect(context.selectedEntities).toEqual(repeated.selectedEntities);
      expect(context.snapshot.evidence).toEqual(repeated.snapshot.evidence);
    });

    it("marks unavailable page collections incomplete and empty-evidence sources unavailable", () => {
      const emptyEnvelope = {
        data: [],
        evidence: [],
        scope: {},
        knowledge_version: "empty",
        pagination: { offset: 0, limit: 100, total: 0, next_offset: null },
      };
      const context = buildOverviewCopilotContext({
        scope: {},
        situations: emptyEnvelope,
        network: null,
        vulnerabilities: null,
        connections: null,
      });

      expect(context.coverage).toEqual({
        connections: {
          visible_count: 0,
          total_count: 0,
          complete: false,
          truncated: false,
        },
        situations: {
          visible_count: 0,
          total_count: 0,
          complete: true,
          truncated: false,
        },
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "situations", status: "unavailable" }),
          expect.objectContaining({ source: "connections", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            section: "coverage",
            status: "unavailable",
            data: expect.objectContaining({
              source_key: "connections",
            }),
          }),
        ]),
      );
    });

    it("trims low-priority evidence deterministically to the snapshot byte limit", () => {
      const records = Array.from({ length: COPILOT_SNAPSHOT_LIMITS.evidenceRows }, (_, index) => ({
        identity: `record-${index.toString().padStart(3, "0")}`,
        namespace: "operations",
        kind: "situation",
        source: "situations/visible",
        priority: index,
        data: {
          title: `Situation ${index}`,
          detail: "x".repeat(900),
        },
      }));
      const input = {
        ...corePageInput,
        records,
        evidence: [],
      };

      const context = buildOverviewCopilotContext(input);
      const repeated = buildOverviewCopilotContext(input);

      expect(new TextEncoder().encode(JSON.stringify(context.snapshot)).length)
        .toBeLessThanOrEqual(COPILOT_SNAPSHOT_LIMITS.snapshotBytes);
      expect(context.snapshot.evidence.length).toBeLessThan(records.length);
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        repeated.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            section: "coverage",
            data: expect.objectContaining({
              retention: expect.objectContaining({
                retained_count: expect.any(Number),
                omitted_count: records.length
                  - context.snapshot.evidence.filter((row) => row.section !== "coverage").length,
                row_limit: COPILOT_SNAPSHOT_LIMITS.evidenceRows,
                byte_limit: COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
              }),
            }),
          }),
        ]),
      );
      expect(context.coverage.situations.complete).toBe(false);
      expect(context.uncertainty).toContain(
        `evidence retention omitted ${
          records.length
          - context.snapshot.evidence.filter((row) => row.section !== "coverage").length
        } rows`,
      );
      expect(normalizeCopilotSnapshotV2(context.snapshot).coverage.complete).toBe(false);
    });

    it.each([64, 65, 66])(
      "reports bounded byte-retention truth at the 65-row neighborhood (%i rows)",
      (rowCount) => {
        const records = Array.from({ length: rowCount }, (_, index) => ({
          identity: `byte-row-${index.toString().padStart(3, "0")}`,
          namespace: "operations",
          kind: "situation",
          source: "situations/visible",
          priority: index,
          data: {
            title: `Situation ${index}`,
            detail: "x".repeat(1900),
          },
        }));
        const context = buildOverviewCopilotContext({
          ...corePageInput,
          records,
          evidence: [],
          coverage: [{
            key: "situations",
            visibleCount: rowCount,
            totalCount: rowCount,
          }],
        });
        const retainedCount = context.snapshot.evidence.filter(
          (row) => row.section !== "coverage",
        ).length;
        const omittedCount = rowCount - retainedCount;
        const coverageRow = context.snapshot.evidence.find(
          (row) => row.section === "coverage",
        );

        expect(coverageRow?.data).toMatchObject({
          retention: {
            retained_count: retainedCount,
            omitted_count: omittedCount,
            row_limit: COPILOT_SNAPSHOT_LIMITS.evidenceRows,
            byte_limit: COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
          },
        });
        expect(context.coverage.situations.complete).toBe(omittedCount === 0);
        expect(normalizeCopilotSnapshotV2(context.snapshot).coverage.complete)
          .toBe(omittedCount === 0);
        if (omittedCount) {
          expect(context.uncertainty).toContain(
            `evidence retention omitted ${omittedCount} rows`,
          );
        }
      },
    );

    it.each([199, 200, 201])(
      "reports bounded row-retention truth at the 200-row neighborhood (%i total rows)",
      (totalRows) => {
        const recordCount = totalRows - 1;
        const records = Array.from({ length: recordCount }, (_, index) => ({
          identity: `limit-row-${index.toString().padStart(3, "0")}`,
          namespace: "operations",
          kind: "situation",
          source: "situations/visible",
          priority: index,
          data: { title: `Situation ${index}` },
        }));
        const context = buildOverviewCopilotContext({
          ...corePageInput,
          records,
          evidence: [],
          coverage: [{
            key: "situations",
            visibleCount: recordCount,
            totalCount: recordCount,
          }],
        });
        const retainedCount = context.snapshot.evidence.filter(
          (row) => row.section !== "coverage",
        ).length;
        const omittedCount = recordCount - retainedCount;
        const coverageRow = context.snapshot.evidence.find(
          (row) => row.section === "coverage",
        );

        expect(context.snapshot.evidence.length)
          .toBeLessThanOrEqual(COPILOT_SNAPSHOT_LIMITS.evidenceRows);
        expect(coverageRow?.data).toMatchObject({
          retention: {
            retained_count: retainedCount,
            omitted_count: omittedCount,
            row_limit: COPILOT_SNAPSHOT_LIMITS.evidenceRows,
            byte_limit: COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
          },
        });
        expect(context.coverage.situations.complete).toBe(omittedCount === 0);
        expect(normalizeCopilotSnapshotV2(context.snapshot).coverage.complete)
          .toBe(omittedCount === 0);
        if (omittedCount) {
          expect(context.uncertainty).toContain(
            `evidence retention omitted ${omittedCount} rows`,
          );
        }
      },
    );
  });

  describe("exposure, CVE detail, and situations Copilot page adapters", () => {
    const exposureInput = {
      scope: { subscription: ["sub-a"] },
      summary: {
        value: {
          cve_count: 12,
          affected_asset_count: 5,
          affected_business_service_count: 3,
          critical_count: 4,
          reachable_server_count: 2,
          internet_exposed_count: 1,
        },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T10:00:00Z",
        evidence: [
          {
            source_engine: "Fabric",
            source_table: "exposure_summary",
            timestamp: "2026-09-07T10:00:00Z",
            confidence: "high" as const,
            freshness: "fresh" as const,
          },
        ],
      },
      patchPriorities: {
        value: [
          {
            priority_id: "patch-1",
            kb_id: "KB5001",
            cve_ids: ["CVE-2026-0001"],
            priority_score: 92,
            affected_server_count: 8,
            recommended_action: "Deploy KB5001",
          },
          {
            priority_id: "patch-2",
            kb_id: "KB5002",
            cve_ids: ["CVE-2026-0002"],
            priority_score: 71,
            affected_server_count: 3,
            recommended_action: "Deploy KB5002",
          },
        ],
        loadedCount: 2,
        totalCount: 6,
        freshness: "partial" as const,
        available: true,
        observedAt: "2026-09-07T09:30:00Z",
      },
      assets: {
        value: [
          {
            asset_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            name: "vm-1",
            resource_type: "Microsoft.Compute/virtualMachines",
            business_service: "Payments",
            application: "Ledger",
            cve_count: 4,
            critical_count: 2,
          },
        ],
        loadedCount: 1,
        totalCount: 3,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:00:00Z",
      },
      riskExceptions: {
        value: [],
        loadedCount: 0,
        totalCount: 0,
        freshness: "unavailable" as const,
        available: false,
      },
    };

    it("preserves exposure vulnerability/asset/patch identities, partial coverage, and unavailable-vs-empty status", () => {
      const context = buildExposureCopilotContext(exposureInput);
      const reordered = buildExposureCopilotContext({
        ...exposureInput,
        patchPriorities: {
          ...exposureInput.patchPriorities,
          value: [...exposureInput.patchPriorities.value].reverse(),
        },
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "exposure",
      });
      // Patch identity is canonical non-ARM; asset identity is canonical ARM.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "patch_priority",
                source_key: "patch-1",
              },
              actionable: false,
              mutation_authorized: false,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage).toMatchObject({
        patch_priorities: {
          visible_count: 2,
          total_count: 6,
          complete: false,
          truncated: true,
        },
        assets: {
          visible_count: 1,
          total_count: 3,
          complete: false,
          truncated: true,
        },
        risk_exceptions: {
          visible_count: 0,
          total_count: 0,
          complete: false,
          truncated: false,
        },
      });
      // Deterministic evidence identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // Unavailable source is distinct from a healthy empty result.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "risk_exceptions", status: "unavailable" }),
          expect.objectContaining({ source: "patch_priorities", status: "partial" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining([
          "patch_priorities coverage is truncated",
          "assets coverage is truncated",
        ]),
      );
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "vulnerability"
        && !/write|update|delete|execute|remediate/i.test(starter.tool ?? ""))).toBe(true);
    });

    const cveInput = {
      scope: { subscription: ["sub-a"] },
      cveId: "CVE-2026-0001",
      cve: {
        cve_id: "CVE-2026-0001",
        title: "Critical RCE",
        description: "Remote code execution",
        severity: "critical",
        cvss: { version: "3.1", base_score: 9.8, vector: "AV:N", severity: "critical" },
        associated_kbs: ["KB5001", "KB5002"],
        epss_score: 0.7,
        epss_percentile: 0.94,
        is_known_exploited: true,
        kev_date_added: "2026-09-01",
        kev_due_date: "2026-09-22",
        kev_ransomware_use: "Known",
      },
      findings: {
        rows: [
          {
            exposure_id: "exp-1",
            target_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            weakness_id: "CVE-2026-0001",
            business_service: "Payments",
            application: "Ledger",
            severity: "critical",
            target_kind: "container_image",
            current_state: "active",
            represented_workload_count: 3,
            total_workload_count: 3,
            missing_kb: "KB5001",
            reachable: true,
          },
        ],
        loadedCount: 1,
        totalCount: 5,
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      attack: {
        graph: {
          cve_id: "CVE-2026-0001",
          nodes: [
            { id: "origin", kind: "origin" as const, label: "Internet" },
            { id: "vm-1", kind: "server" as const, label: "vm-1", reachable: true },
          ],
          edges: [{ source: "origin", target: "vm-1", label: "reaches" }],
          reachable_server_count: 1,
          internet_exposed: true,
        },
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      sources: [
        { key: "nvd", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T08:00:00Z" },
        { key: "epss", freshness: "partial" as const, available: true, observedAt: "2026-09-07T07:00:00Z" },
        { key: "kev", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T06:00:00Z" },
        { key: "msrc", freshness: "unavailable" as const, available: false },
      ],
      filters: { weakness_id: ["CVE-2026-0001"], page: ["1"] },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "cve_findings",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries the canonical non-ARM CVE identity, KB/finding identities, source freshness, and pagination coverage", () => {
      const context = buildCveDetailCopilotContext(cveInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "cve:CVE-2026-0001",
      });
      // The CVE itself is a canonical non-ARM (domain) selected identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "vulnerability",
          kind: "cve",
          source_key: "CVE-2026-0001",
        },
      ]);
      // CVE is not an ARM resource, so it must not leak into selected_resources.
      expect(context.snapshot.selected_resources).toEqual([]);
      // KB identities are retained.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              epss_percentile: 0.94,
              kev_due_date: "2026-09-22",
              kev_ransomware_use: "Known",
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "kb",
                source_key: "KB5001",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.findings).toMatchObject({
        visible_count: 1,
        total_count: 5,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "nvd", status: "fresh" }),
          expect.objectContaining({ source: "epss", status: "partial" }),
          expect.objectContaining({ source: "msrc", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.filters).toMatchObject({
        weakness_id: ["CVE-2026-0001"],
        page: ["1"],
      });
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("drops stale CVE data and binds the starter to the visible route CVE", () => {
      const context = buildCveDetailCopilotContext({
        ...cveInput,
        cveId: "cve-2026-13221",
        cve: {
          ...cveInput.cve,
          cve_id: "CVE-2026-0001",
        },
        findings: {
          ...cveInput.findings,
          rows: cveInput.findings.rows.map((row) => ({
            ...row,
            weakness_id: "CVE-2026-0001",
          })),
        },
      });

      expect(context.snapshot.page_id).toBe("cve:CVE-2026-13221");
      expect(JSON.stringify(context.snapshot.evidence)).not.toContain("CVE-2026-0001");
      expect(context.starterQuestions[0]).toMatchObject({
        label: "Explain CVE-2026-13221",
        toolArguments: { cve_id: "CVE-2026-13221" },
      });
    });

    it("distinguishes an unavailable CVE provider from a healthy empty finding set", () => {
      const context = buildCveDetailCopilotContext({
        ...cveInput,
        findings: {
          ...cveInput.findings,
          rows: [],
          loadedCount: 0,
          totalCount: 0,
          available: true,
        },
        attack: {
          ...cveInput.attack,
          graph: null,
          available: false,
          freshness: "unavailable" as const,
        },
      });

      expect(context.coverage.findings).toMatchObject({
        visible_count: 0,
        total_count: 0,
        complete: true,
        truncated: false,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "attack_path", status: "unavailable" }),
        ]),
      );
    });

    it("omits attack-path context when the page does not supply an attack section", () => {
      const context = buildCveDetailCopilotContext({ ...cveInput, attack: undefined });

      expect(context.coverage).not.toHaveProperty("attack_path");
      expect(context.snapshot.freshness.some((item) => item.source === "attack_path")).toBe(false);
      expect(context.snapshot.evidence.some((item) =>
        JSON.stringify(item).includes("attack_path"))).toBe(false);
      expect(context.starterQuestions.some((starter) =>
        starter.tool === "cve_attack_path")).toBe(false);
    });


    const situationsInput = {
      scope: { subscription: ["sub-a"] },
      situations: [
        {
          situation_id: "situation://p1",
          resource_id: "situation://p1",
          title: "Database unavailable",
          situation_type: "service_health",
          lifecycle_state: "open",
          severity: "critical",
          priority: "P1" as const,
          scope: { subscription: ["sub-a"] },
          owner: "SRE",
          support_team: "Platform",
          affected_resource_ids: ["/subscriptions/sub-a/db"],
          linked_evidence_ids: [],
          started_at: "2026-08-25T01:00:00Z",
          last_observed_at: "2026-08-25T01:00:00Z",
          evidence_state: "corroborated",
          warnings: [],
          contradiction_ids: [],
          unknowns: [],
          run_id: "run-1",
        },
      ],
      query: "payments",
      priority: "P1" as const,
      page: 1,
      pageSize: 25,
      totalCount: 40,
      nextOffset: 50,
      selectedSituationId: "situation://p1",
      available: true,
      observedAt: "2026-08-25T01:00:00Z",
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "situations",
          timestamp: "2026-08-25T01:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("preserves situation filters, selected identity, source trust, and visible/total pagination", () => {
      const context = buildSituationsCopilotContext(situationsInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "incident",
        page_id: "situations",
        filters: {
          query: ["payments"],
          priority: ["P1"],
          page: ["1"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "operations",
          kind: "situation",
          source_key: "situation://p1",
        },
      ]);
      expect(context.coverage.situations).toMatchObject({
        visible_count: 1,
        total_count: 40,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "operations",
                kind: "situation",
                source_key: "situation://p1",
              },
              selected: true,
            }),
          }),
        ]),
      );
      expect(context.starterQuestions.length).toBeGreaterThan(0);
    });

    it("keeps an unavailable situations provider distinct from an empty authorized queue", () => {
      const unavailable = buildSituationsCopilotContext({
        ...situationsInput,
        situations: [],
        totalCount: 0,
        nextOffset: null,
        selectedSituationId: null,
        available: false,
        evidence: [],
      });
      const empty = buildSituationsCopilotContext({
        ...situationsInput,
        situations: [],
        totalCount: 0,
        nextOffset: null,
        selectedSituationId: null,
        available: true,
        evidence: [],
      });

      expect(unavailable.coverage.situations.complete).toBe(false);
      expect(empty.coverage.situations.complete).toBe(true);
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "situations", status: "unavailable" }),
        ]),
      );
    });

    it("does not claim fresh Situations evidence when an empty live envelope reports unknown freshness", () => {
      const context = buildSituationsCopilotContext({
        ...situationsInput,
        situations: [],
        totalCount: 0,
        nextOffset: null,
        selectedSituationId: null,
        available: true,
        observedAt: "",
        evidence: [
          {
            source_engine: "aiops.situations",
            source_table: "silver_situations",
            timestamp: "",
            confidence: "unknown",
            freshness: "unknown",
          },
        ],
      });

      expect(context.coverage.situations).toMatchObject({
        visible_count: 0,
        total_count: 0,
        complete: true,
      });
      expect(context.snapshot.freshness).toEqual([
        {
          source: "situations",
          observed_at: "unknown",
          status: "unavailable",
        },
      ]);
    });
  });

  describe("remediation Copilot page adapter", () => {
    type RemediationContext = ReturnType<typeof buildRemediationCopilotContext>;
    const planRow = (ctx: RemediationContext) =>
      ctx.snapshot.evidence.find((row) => row.data.claim_type === "remediation_plan");
    const historicalRows = (ctx: RemediationContext) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === "historical_finding");

    const remediationInput = {
      scope: { subscription: ["sub-a"] },
      selectedPlan: {
        plan_id: "plan-1",
        action_id: "controlled-patch-recovery",
        action_version: "version-1",
        title: "Patch payroll database",
        status: "Draft - Approval Required",
        family: "patch",
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        resource_type: "Microsoft.Compute/virtualMachines",
        resource_name: "vm-1",
        snapshot_hash: "snapshot-hash-1",
      },
      eligibility: {
        plan_executable: false,
        plan_ineligibility_reason: "not_approved",
        can_operate: false,
        operate_ineligible_reason: "approval_not_current",
        can_approve: true,
        approval_current: false,
        approval_status: "none",
        has_executable_preview: true,
        recommended_step: "approve",
      },
      requirements: [
        {
          policy_id: "change-control",
          role: "Change Manager",
          stage: "Planning",
          satisfied: false,
          unmet_reason: "pending",
        },
      ],
      execution: null,
      blockers: [
        {
          code: "stale_approval",
          step: "approve",
        },
      ],
      evidence: [
        {
          source_engine: "ARG",
          source_table: "securityresources",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
      historicalEvidence: [
        {
          key: "thread-finding-1",
          summary: "Earlier thread said this was already runnable",
          observedAt: "2026-09-01T00:00:00Z",
        },
      ],
      coverage: { visiblePlanCount: 2, totalPlanCount: 6 },
      sourceStatuses: [
        {
          source: "plans",
          availability: "available" as const,
          freshness: "fresh",
          observedAt: "2026-09-07T10:00:00Z",
        },
        { source: "assessment", availability: "degraded" as const, freshness: "stale" },
      ],
    };

    it("binds current server plan identity, eligibility, coverage, and freshness, labeling carried history non-current", () => {
      const context = buildRemediationCopilotContext(remediationInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "remediation",
        page_id: "remediation",
      });
      // Selected plan carried with current, read-only server eligibility facts.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "remediation_plan",
              current: true,
              actionable: false,
              mutation_authorized: false,
              plan_executable: false,
              can_operate: false,
              can_approve: true,
              approval_current: false,
              approval_status: "none",
              has_executable_preview: true,
              recommended_step: "approve",
              workflow_blockers: ["approve:stale_approval"],
            }),
          }),
        ]),
      );
      // Plan resource identity is a canonical ARM entity.
      expect(planRow(context)?.data.entity).toMatchObject({
        type: "azure",
        resource_id:
          "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
      });
      // Approval requirement lifecycle is carried as current context.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "approval_requirement",
              current: true,
              satisfied: false,
              role: "Change Manager",
            }),
          }),
        ]),
      );
      // Historical carried evidence is explicitly non-current and inert.
      expect(historicalRows(context)).toHaveLength(1);
      expect(historicalRows(context).every((row) =>
        row.data.current === false
        && row.data.actionable === false
        && row.data.mutation_authorized === false)).toBe(true);
      // Visible/total plan coverage and degraded freshness are projected.
      expect(context.coverage).toMatchObject({
        plans: { visible_count: 2, total_count: 6, complete: false, truncated: true },
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "stale" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["plans coverage is truncated"]),
      );
    });

    it("lets current server eligibility override historical thread context", () => {
      const withoutHistory = buildRemediationCopilotContext({
        ...remediationInput,
        historicalEvidence: [],
      });
      const withStaleOperableClaim = buildRemediationCopilotContext({
        ...remediationInput,
        historicalEvidence: [
          {
            key: "thread-finding-1",
            summary: "Copilot previously reported can_operate:true",
            observedAt: "2026-09-01T00:00:00Z",
          },
          {
            key: "thread-finding-2",
            summary: "approved earlier in the thread",
            observedAt: "2026-09-02T00:00:00Z",
          },
        ],
      });

      // Eligibility facts come only from the current server projection.
      expect(planRow(withStaleOperableClaim)?.data).toMatchObject({
        can_operate: false,
        can_approve: true,
        approval_current: false,
        plan_executable: false,
      });
      expect(planRow(withStaleOperableClaim)?.data.can_operate).toEqual(
        planRow(withoutHistory)?.data.can_operate,
      );
      // No carried history row is ever actionable or mutation-authorized.
      expect(historicalRows(withStaleOperableClaim).every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("exposes no Copilot mutation path across plan, approval, execution, or history evidence", () => {
      const context = buildRemediationCopilotContext({
        ...remediationInput,
        execution: {
          execution_id: "RME-1",
          status: "running",
          retryable: false,
          cancellable: false,
          supersedable: false,
          remaining_attempts: 2,
        },
      });

      expect(context.snapshot.evidence.length).toBeGreaterThan(0);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
      // Execution state is descriptive, current, and non-authorizing.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "remediation_execution",
              current: true,
              status: "running",
              actionable: false,
              mutation_authorized: false,
            }),
          }),
        ]),
      );
      // Advisory starter hints only: no approve/execute/run/write tool.
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "remediation"
        && !/approve|execute|run|write|update|delete|remediate|cancel|retry|supersede/i.test(
          starter.tool ?? "",
        ))).toBe(true);
    });

    it("retains deterministic cited server evidence independent of optional narration", () => {
      const context = buildRemediationCopilotContext(remediationInput);
      expect(context.snapshot.evidence.some((row) =>
        row.data.claim_type === "source_observation")).toBe(true);
      expect(context.snapshot.evidence.some((row) =>
        row.data.claim_type === "remediation_plan")).toBe(true);
    });

    it("keeps a bounded context when no plan is selected yet", () => {
      const context = buildRemediationCopilotContext({
        ...remediationInput,
        selectedPlan: null,
        eligibility: null,
        requirements: [],
        execution: null,
        historicalEvidence: [],
        coverage: { visiblePlanCount: 0, totalPlanCount: 0 },
      });
      expect(context.snapshot.page_kind).toBe("remediation");
      expect(planRow(context)).toBeUndefined();
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("rejects workflow blocker overflow instead of omitting a safety fact", () => {
      expect(() => buildRemediationCopilotContext({
        ...remediationInput,
        blockers: Array.from({ length: 17 }, (_, index) => ({
          code: `blocker_${index}`,
          step: "review",
        })),
      })).toThrow("remediation workflow blockers exceeds limit of 16");
    });
  });

  describe("defender posture, KB detail, and patch priority Copilot page adapters", () => {
    type CoreContext = ReturnType<typeof buildDefenderPostureCopilotContext>;
    const rowByClaim = (ctx: CoreContext, claim: string) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

    const defenderInput = {
      scope: { subscription: ["sub-a"] },
      selectedAssetId:
        "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
      overview: {
        value: {
          active_alert_count: 7,
          critical_alert_count: 2,
          attack_path_count: 3,
          unhealthy_recommendation_count: 11,
          vulnerable_container_image_count: 4,
          container_image_cve_count: 19,
        },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T10:00:00Z",
        evidence: [
          {
            source_engine: "ARG",
            source_table: "securityresources",
            timestamp: "2026-09-07T10:00:00Z",
            confidence: "high" as const,
            freshness: "fresh" as const,
          },
        ],
      },
      secureScore: {
        value: { current: 42, max: 60, percentage: 70 },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:45:00Z",
      },
      findings: {
        value: [
          {
            assessment_id: "assess-1",
            asset_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            asset_name: "vm-1",
            resource_type: "Microsoft.Compute/virtualMachines",
            defender_plan: "Servers",
            status: "Unhealthy",
            severity: "High",
            recommendation: "Enable endpoint protection",
            business_service: "Payments",
            last_assessed_at: "2026-09-07T09:00:00Z",
          },
        ],
        loadedCount: 1,
        totalCount: 5,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:00:00Z",
      },
      alerts: {
        value: [
          { id: "alert-1", title: "Suspicious sign-in", severity: "High", status: "Active" },
        ],
        loadedCount: 1,
        totalCount: 7,
        freshness: "partial" as const,
        available: true,
        observedAt: "2026-09-07T08:00:00Z",
      },
      attackPaths: {
        value: [
          { id: "path-1", title: "Internet to DB", potentialImpact: "Data exfiltration", nodeCount: 4 },
        ],
        loadedCount: 1,
        totalCount: 3,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T08:30:00Z",
      },
      containers: {
        value: [],
        loadedCount: 0,
        totalCount: 0,
        freshness: "unavailable" as const,
        available: false,
      },
      evidence: [],
    };

    it("binds selected Defender asset, posture aggregates, coverage, and unavailable-vs-empty status", () => {
      const context = buildDefenderPostureCopilotContext(defenderInput);
      const reordered = buildDefenderPostureCopilotContext({
        ...defenderInput,
        findings: {
          ...defenderInput.findings,
          value: [...defenderInput.findings.value].reverse(),
        },
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "defender-posture",
      });
      // Selected finding asset is a canonical ARM selected entity.
      expect(context.selectedEntities).toEqual([
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
        },
      ]);
      // Posture aggregate carried as descriptive, non-actionable evidence.
      expect(rowByClaim(context, "defender_overview")[0]?.data).toMatchObject({
        active_alert_count: 7,
        critical_alert_count: 2,
        attack_path_count: 3,
        unhealthy_recommendation_count: 11,
        actionable: false,
        mutation_authorized: false,
      });
      // Visible/total coverage across sections; empty is not truncated.
      expect(context.coverage).toMatchObject({
        findings: { visible_count: 1, total_count: 5, complete: false, truncated: true },
        alerts: { visible_count: 1, total_count: 7, complete: false, truncated: true },
        attack_paths: { visible_count: 1, total_count: 3, complete: false, truncated: true },
        containers: { visible_count: 0, total_count: 0, complete: false, truncated: false },
      });
      // Unavailable container feed is distinct from a healthy empty result.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "containers", status: "unavailable" }),
          expect.objectContaining({ source: "alerts", status: "partial" }),
          expect.objectContaining({ source: "findings", status: "fresh" }),
        ]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // No definitive safety claim: everything non-actionable/non-authorized.
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
      // Advisory specialist hints only.
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.starterQuestions.every((starter) =>
        ["vulnerability", "remediation"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
    });

    const kbInput = {
      scope: { subscription: ["sub-a"] },
      kbId: "KB5001",
      kb: {
        kb_id: "KB5001",
        title: "September cumulative update",
        product: "Windows Server 2022",
        severity: "critical",
        published_at: "2026-09-01T00:00:00Z",
        target_date: "2026-09-30",
        cve_ids: ["CVE-2026-0001", "CVE-2026-0002"],
        affected_servers: ["srv-1", "srv-2"],
        affected_server_count: 137,
        affected_servers_truncated: true,
        affected_business_services: ["Payments"],
      },
      findings: {
        rows: [
          {
            target_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            server_id: "srv-1",
            cve_id: "CVE-2026-0001",
            product_name: "Windows Server 2022",
            target_date: "2026-09-30",
            application: "Ledger",
            business_service: "Payments",
            severity: "critical",
            reachable: true,
          },
        ],
        loadedCount: 1,
        totalCount: 4,
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      sources: [
        { key: "msrc", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T08:00:00Z" },
        { key: "nvd", freshness: "partial" as const, available: true, observedAt: "2026-09-07T07:00:00Z" },
        { key: "epss", freshness: "unavailable" as const, available: false },
      ],
      filters: { target_kind: ["server"], page: ["1"] },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "kb_findings",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries the canonical non-ARM KB identity, CVE/machine identities, freshness, and coverage", () => {
      const context = buildKbDetailCopilotContext(kbInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "kb:KB5001",
      });
      // KB is a canonical non-ARM (domain) selected identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "vulnerability",
          kind: "kb",
          source_key: "KB5001",
        },
      ]);
      // KB must not leak into scope-validated resource fields.
      expect(context.snapshot.selected_resources).toEqual([]);
      // CVE identities retained.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              product: "Windows Server 2022",
              published_at: "2026-09-01T00:00:00Z",
              target_date: "2026-09-30",
              affected_server_count: 137,
              affected_servers_truncated: true,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "cve",
                source_key: "CVE-2026-0001",
              },
            }),
          }),
          // Affected machine finding is a canonical ARM identity.
          expect.objectContaining({
            data: expect.objectContaining({
              product_name: "Windows Server 2022",
              target_date: "2026-09-30",
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.findings).toMatchObject({
        visible_count: 1,
        total_count: 4,
        complete: false,
        truncated: true,
      });
      // Lifecycle enrichment freshness downgrades; unavailable distinct.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "msrc", status: "fresh" }),
          expect.objectContaining({ source: "nvd", status: "partial" }),
          expect.objectContaining({ source: "epss", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.filters).toMatchObject({ target_kind: ["server"], page: ["1"] });
      const canonical = normalizeCopilotSnapshotV2(context.snapshot);
      expect(canonical.filters).toEqual({
        page: ["1"],
        target_kind: ["server"],
      });
      expect(canonical.query).toBe("");
      expect(canonical.generation_id).toMatch(/^generation:[a-f0-9]{64}$/);
      // Patch specialist hints, never mutating.
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "patch"
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.starterQuestions).toEqual([
        {
          label: "Explain KB5001 and the CVEs it remediates",
          specialistId: "patch",
          tool: "kb_detail",
          toolArguments: { kb_id: "KB5001" },
        },
        {
          label: "Which product and publication date apply to KB5001?",
          specialistId: "patch",
          tool: "kb_detail",
          toolArguments: { kb_id: "KB5001" },
        },
        {
          label: "What should we patch first for KB5001?",
          specialistId: "patch",
          tool: "patch_priorities",
          toolArguments: {},
        },
      ]);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("distinguishes an unavailable KB provider from a healthy empty finding set", () => {
      const unavailable = buildKbDetailCopilotContext({ ...kbInput, kb: null });
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "kb", status: "unavailable" }),
        ]),
      );
      const empty = buildKbDetailCopilotContext({
        ...kbInput,
        findings: { ...kbInput.findings, rows: [], loadedCount: 0, totalCount: 0 },
      });
      expect(empty.coverage.findings).toMatchObject({
        visible_count: 0,
        total_count: 0,
        complete: true,
        truncated: false,
      });
    });

    const patchInput = {
      scope: { subscription: ["sub-a"] },
      rows: [
        {
          exposure_id: "exp-1",
          target_id:
            "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
          weakness_id: "CVE-2026-0001",
          missing_kb: "KB5001",
          server_id: "srv-1",
          application: "Ledger",
          business_service: "Payments",
          severity: "critical",
          priority_score: 92,
          recommendation: "Deploy KB5001",
          sla_state: "overdue",
          sla_overdue: true,
        },
        {
          exposure_id: "exp-2",
          target_id: "srv-2",
          weakness_id: "CVE-2026-0002",
          missing_kb: "KB5002",
          severity: "high",
          priority_score: 71,
          sla_state: "open",
          sla_overdue: false,
        },
      ],
      loadedCount: 2,
      totalCount: 8,
      available: true,
      freshness: "partial" as const,
      observedAt: "2026-09-07T09:30:00Z",
      selectedId: "exp-1",
      filters: { source_family: ["patch"], page: ["1"] },
      sort: { priority_score: "desc" as const },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "patch_priorities",
          timestamp: "2026-09-07T09:30:00Z",
          confidence: "high" as const,
          freshness: "aging" as const,
        },
      ],
      sourceStatuses: [
        { source: "patch_priorities", freshness: "partial", observedAt: "2026-09-07T09:30:00Z" },
      ],
    };

    it("binds patch priority KB/CVE/machine identities, SLA evidence, freshness, and truncation", () => {
      const context = buildPatchPrioritiesCopilotContext(patchInput);
      const reordered = buildPatchPrioritiesCopilotContext({
        ...patchInput,
        rows: [...patchInput.rows].reverse(),
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "patch-priorities",
      });
      // Selected patch row with a canonical ARM machine identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
        },
      ]);
      // KB/CVE evidence and SLA facts retained and non-actionable.
      const selectedPatch = rowByClaim(context, "patch_priority").find(
        (row) => row.data.exposure_id === "exp-1",
      );
      expect(selectedPatch?.data).toMatchObject({
        missing_kb: "KB5001",
        weakness_id: "CVE-2026-0001",
        priority_score: 92,
        sla_overdue: true,
        actionable: false,
        mutation_authorized: false,
      });
      expect(context.coverage.patch_priorities).toMatchObject({
        visible_count: 2,
        total_count: 8,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "patch_priorities", status: "partial" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["patch_priorities coverage is truncated"]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "patch"
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.starterQuestions).toEqual([
        {
          label: "What is the top KB and why is it ranked first?",
          specialistId: "patch",
          tool: "patch_priorities",
          toolArguments: {},
        },
        {
          label: "Which product and publication date apply to the top KB?",
          specialistId: "patch",
          tool: "patch_priorities",
          toolArguments: {},
        },
        {
          label: "What action is recommended for the top KB?",
          specialistId: "patch",
          tool: "patch_priorities",
          toolArguments: {},
        },
      ]);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });
  });

  describe("changes and predeploy Copilot page adapters", () => {
    type CoreContext = ReturnType<typeof buildChangesCopilotContext>;
    const rowByClaim = (ctx: CoreContext, claim: string) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

    const changesInput = {
      scope: { subscription: ["sub-a"] },
      changes: [
        {
          event_id: "evt-1",
          incident_id: "inc-1",
          incident_title: "Payment latency spike",
          event_type: "deployment_change",
          summary: "Deployed ledger v42",
          source: "github",
          timestamp: "2026-09-07T10:00:00Z",
          business_services: ["Payments"],
        },
        {
          event_id: "evt-2",
          incident_id: "inc-2",
          incident_title: "DNS flap",
          event_type: "config_change",
          summary: "Updated firewall rule",
          source: "terraform",
          timestamp: "2026-09-07T09:00:00Z",
          business_services: ["Networking"],
        },
      ],
      loadedCount: 2,
      totalCount: 6,
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-09-07T10:00:00Z",
      selectedId: "evt-1",
      filters: { event_type: ["change"], page: ["1"] },
      evidence: [
        {
          source_engine: "Situations",
          source_table: "incident_timeline",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "medium" as const,
          freshness: "fresh" as const,
        },
      ],
      sourceStatuses: [
        { source: "changes", freshness: "fresh", observedAt: "2026-09-07T10:00:00Z" },
      ],
    };

    it("binds correlated change identities, proximity basis, coverage, and cross-domain hints", () => {
      const context = buildChangesCopilotContext(changesInput);
      const reordered = buildChangesCopilotContext({
        ...changesInput,
        changes: [...changesInput.changes].reverse(),
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "incident",
        page_id: "changes",
      });
      // Change correlation is a stable domain identity.
      const selectedChange = rowByClaim(context, "change_correlation").find(
        (row) => row.data.event_id === "evt-1",
      );
      expect(selectedChange?.data).toMatchObject({
        entity: {
          type: "domain",
          namespace: "change",
          kind: "change_correlation",
          source_key: "evt-1",
        },
        incident_id: "inc-1",
        event_type: "deployment_change",
        // Correlation is not causation: proximity only, never confirmed.
        correlation_basis: "temporal_proximity",
        confirmed: false,
        actionable: false,
        mutation_authorized: false,
      });
      expect(context.coverage.changes).toMatchObject({
        visible_count: 2,
        total_count: 6,
        complete: false,
        truncated: true,
      });
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["changes coverage is truncated"]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // Cross-domain starters: change list can select change plus
      // incident/remediation specialists, and none mutate state.
      const specialists = new Set(context.starterQuestions.map((s) => s.specialistId));
      expect(specialists.has("incident")).toBe(true);
      expect(specialists.has("remediation")).toBe(true);
      expect(context.starterQuestions.every((starter) =>
        ["incident", "remediation", "vulnerability"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("binds default Changes freshness to the loaded evidence source and timestamp", () => {
      const context = buildChangesCopilotContext({
        ...changesInput,
        changes: [],
        loadedCount: 0,
        totalCount: 0,
        selectedId: null,
        observedAt: "2026-09-07T10:00:00Z",
        sourceStatuses: undefined,
      });

      expect(context.snapshot.freshness).toEqual([
        {
          source: "Situations/incident_timeline",
          observed_at: "2026-09-07T10:00:00Z",
          status: "fresh",
        },
      ]);
    });

    const predeployInput = {
      scope: { subscription: ["sub-a"] },
      change: {
        change_id: "chg-1",
        title: "Scale payments API",
        author: "release-bot",
        source: "terraform_plan",
        target_environment: "prod",
        resource_change_count: 3,
      },
      simulation: {
        highest_severity: "high",
        simulated_domains: ["compute", "network"],
        by_severity: { high: 1, medium: 2 },
        effect_count: 3,
        confirmed_outcome: false,
      },
      risk: {
        score: 68,
        level: "elevated",
        confidence: "medium",
        confirmed_cause: false,
      },
      cab: {
        verdict: "review_required",
        risk_level: "elevated",
        required_approvals: ["Change Manager"],
        confirmed_cause: false,
      },
      impactedResources: [
        {
          resource_id:
            "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
          resource_name: "vm-1",
          business_service: "Payments",
          environment: "prod",
          relationship: "depends_on",
        },
      ],
      impactedTotalCount: 5,
      impactedTruncated: true,
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-09-07T10:00:00Z",
      unknowns: ["Downstream DNS effect not simulated"],
      evidence: [
        {
          source_engine: "Assessment",
          source_table: "change_assessment",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "medium" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries predeploy simulation/risk/CAB as predicted, never observed, with impacted-resource coverage", () => {
      const context = buildPredeployCopilotContext(predeployInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "governance",
        page_id: "predeploy",
      });
      // Proposed change is the selected domain identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "change",
          kind: "proposed_change",
          source_key: "chg-1",
        },
      ]);
      // Simulation/risk/CAB are explicitly predicted, not observed outcomes.
      const simulation = rowByClaim(context, "change_simulation")[0]?.data;
      expect(simulation).toMatchObject({
        highest_severity: "high",
        confirmed_outcome: false,
        predicted: true,
        observed: false,
        actionable: false,
        mutation_authorized: false,
      });
      const risk = rowByClaim(context, "change_risk")[0]?.data;
      expect(risk).toMatchObject({ score: 68, confirmed_cause: false, predicted: true, observed: false });
      const cab = rowByClaim(context, "cab_recommendation")[0]?.data;
      expect(cab).toMatchObject({
        verdict: "review_required",
        confirmed_cause: false,
        predicted: true,
        observed: false,
      });
      // Impacted resource is a canonical ARM identity.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "impacted_resource",
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.impacted_resources).toMatchObject({
        visible_count: 1,
        total_count: 5,
        complete: false,
        truncated: true,
      });
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["impacted_resources coverage is truncated"]),
      );
      // Cross-domain hints reach incident/remediation specialists; none mutate.
      const specialists = new Set(context.starterQuestions.map((s) => s.specialistId));
      expect(specialists.has("remediation")).toBe(true);
      expect(context.starterQuestions.every((starter) =>
        !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("keeps healthy-empty predeploy distinct from unavailable assessment state", () => {
      const emptyInput = {
        ...predeployInput,
        change: null,
        simulation: null,
        risk: null,
        cab: null,
        impactedResources: [],
        impactedTotalCount: 0,
        impactedTruncated: false,
      };
      const healthyEmpty = buildPredeployCopilotContext({
        ...emptyInput,
        available: true,
        freshness: "fresh" as const,
      });
      const unavailable = buildPredeployCopilotContext({
        ...emptyInput,
        available: false,
        freshness: "unavailable" as const,
      });
      expect(healthyEmpty.snapshot.page_id).toBe("predeploy");
      expect(rowByClaim(healthyEmpty, "proposed_change")).toHaveLength(0);
      expect(healthyEmpty.coverage.impacted_resources.complete).toBe(true);
      expect(unavailable.coverage.impacted_resources.complete).toBe(false);
      expect(healthyEmpty.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "fresh" }),
        ]),
      );
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "unavailable" }),
        ]),
      );
      expect(unavailable.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });
  });

  it("matches the server bounds exactly", () => {
    expect(COPILOT_SNAPSHOT_LIMITS).toEqual({
      snapshotBytes: 128 * 1024,
      selectedEntities: 50,
      evidenceRows: 200,
      evidenceRowBytes: 8 * 1024,
      freshnessRecords: 32,
      evidenceCitations: 32,
      materialClaims: 200,
    });
  });

  it("normalizes an integrated remediation snapshot to the strict v2 wire shape", () => {
      const legacy = buildRemediationCopilotContext({
        ...corePageInput,
        filters: { view: ["remediation"] },
      }).snapshot;

      const normalized = normalizeCopilotSnapshotV2(legacy);

      expect(normalized).toMatchObject({
        version: "2",
        page_kind: "remediation",
        page_id: "remediation",
        coverage: {
          visible_count: 2,
          total_count: 5,
          complete: false,
        },
        selected_entities: expect.any(Array),
        filters: { view: ["remediation"] },
        query: "",
        generation_id: expect.stringMatching(/^generation:[a-f0-9]{64}$/),
        material_claims: expect.arrayContaining([
          expect.objectContaining({
            evidence_refs: [expect.stringMatching(/^evidence:/)],
            requires_complete_coverage: false,
          }),
        ]),
      });
      expect(normalized).not.toHaveProperty("scope");
      expect(normalized).not.toHaveProperty("question");
      expect(normalized.evidence.every((row) =>
        row.actionable === false
        && row.citations.length === 0
        && Boolean(row.entity)
        && Boolean(row.source_key))).toBe(true);
    });

  it.each([
    ["/", "resource", "operations-overview", "overview"],
    ["/network", "network", "network-topology", "network"],
    ["/compliance", "governance", "compliance-posture", "compliance"],
    ["/exposure", "vulnerability", "exposure", "exposure"],
    ["/exposure/cves/[id]", "vulnerability", "cve:CVE-2026-0001", "cve_detail"],
    ["/exposure/defender-posture", "vulnerability", "defender-posture", "defender_posture"],
    ["/exposure/kbs/[id]", "vulnerability", "kb:KB5000001", "kb_detail"],
    ["/exposure/patch-priorities", "vulnerability", "patch-priorities", "patch_priorities"],
    ["/situations", "incident", "situations", "situations"],
    ["/situations/[id]", "incident", "situation:situation-1", "situation_detail"],
    ["/changes", "incident", "changes", "changes"],
    ["/changes/predeploy", "governance", "predeploy", "changes_predeploy"],
    ["/connections", "resource", "connections", "connections"],
    ["/connections/fabric", "resource", "fabric-medallion", "connections_fabric"],
    ["/governance", "governance", "governance", "governance"],
    ["/identity", "governance", "identity", "identity"],
    ["/finops", "governance", "finops", "finops"],
    ["/remediation", "remediation", "remediation", "remediation"],
    ["/resource-health", "resource", "resource-health", "resource_health"],
    ["/services", "resource", "services", "services"],
    ["/services/[name]", "resource", "service:payments", "service_detail"],
    ["/twin", "network", "twin", "twin"],
  ] satisfies Array<[string, CopilotPageKind, string, CopilotPageKindV2]>)(
    "maps free-form legacy adapter output for %s to exact v2 page kind %s",
    (route, legacyPageKind, pageId, expectedPageKind) => {
      const legacy: CopilotPageSnapshot = {
        version: "1",
        page_kind: legacyPageKind,
        page_id: pageId,
        selected_resources: [],
        filters: {},
        freshness: [],
        scope: { declared: { subscription: ["sub-a"] }, authorized: true },
        evidence: [],
        question: "Tell me what matters on this page.",
        rechecks: [],
      };

      expect(normalizeCopilotSnapshotV2(legacy).page_kind).toBe(expectedPageKind);
      expect(COPILOT_ROUTE_DISPOSITIONS[route]).toMatchObject({
        kind: "integrated",
        pageKind: expectedPageKind,
      });
    },
  );

  it("keeps the inventory adapter's exact v2 page kind without a routing hint", () => {
    const inventory = buildInventoryCopilotContext(baseInput).snapshot;

    expect(normalizeCopilotSnapshotV2(inventory).page_kind).toBe("inventory");
    expect(COPILOT_ROUTE_DISPOSITIONS["/inventory"]).toMatchObject({
      kind: "integrated",
      pageKind: "inventory",
    });
  });

  it("does not fabricate legacy coverage from arbitrary evidence rows", () => {
    const legacy: CopilotPageSnapshot = {
      version: "1",
      page_kind: "resource",
      page_id: "services",
      selected_resources: [],
      filters: {},
      freshness: [],
      scope: { declared: { subscription: ["sub-a"] }, authorized: true },
      evidence: [{
        evidence_id: "service:one",
        section: "services",
        status: "ok",
        data: { name: "payments" },
      }],
      question: "Summarize this page.",
      rechecks: [],
    };

    expect(normalizeCopilotSnapshotV2(legacy).coverage).toEqual({
      visible_count: 0,
      total_count: 0,
      complete: false,
    });
  });

  it.each([
      [127, true],
      [128, true],
      [129, false],
    ])(
      "enforces the shared source character boundary at %i characters",
      (sourceLength, accepted) => {
        const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
        snapshot.evidence[0] = {
          ...snapshot.evidence[0],
          source: "界".repeat(sourceLength),
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/source/i);
      },
    );

  it.each([
      [8, true],
      [9, true],
      [10, false],
    ])(
      "enforces the shared 8191/8192/8193-byte UTF-8 row boundary",
      (suffixLength, accepted) => {
        const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
        snapshot.evidence[0] = {
          ...snapshot.evidence[0],
          data: { blob: `${"😀".repeat(681)}${"x".repeat(suffixLength)}` },
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/evidence row/i);
      },
    );

  it.each([
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows - 1, true],
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows, true],
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1, false],
    ])(
      "enforces the shared evidence-list structural boundary at %i rows",
      (rowCount, accepted) => {
        const base = buildInventoryCopilotContext(baseInput).snapshot;
        const template = base.evidence[0];
        const snapshot = {
          ...base,
          coverage: {
            visible_count: rowCount,
            total_count: rowCount,
            complete: true,
          },
          evidence: Array.from({ length: rowCount }, (_, index) => ({
            ...template,
            evidence_id: `row-${index}`,
            source_key: `row-${index}`,
            entity: {
              type: "domain" as const,
              namespace: "inventory",
              kind: "row",
              source_key: `row-${index}`,
            },
          })),
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/evidence rows/i);
      },
    );
  it("builds the complete strict v2 wire contract without authority fields", () => {
    const context = buildInventoryCopilotContext(baseInput);

    expect(context.requestedScope).toEqual({
      subscription: ["sub-a"],
    });
    expect(context.snapshot).toMatchObject({
      version: "2",
      page_kind: "inventory",
      page_id: "inventory:os",
      coverage: {
        visible_count: 2,
        total_count: 4,
        complete: false,
      },
      material_claims: [],
    });
    expect(context.snapshot).not.toHaveProperty("authorized");
    expect(context.snapshot.selected_entities).toEqual([
      {
        type: "domain",
        namespace: "inventory",
        kind: "os_group",
        source_key: "Windows Server|2019",
      },
    ]);
    expect(context.snapshot.evidence[0]).toMatchObject({
      source_key: expect.any(String),
      entity: expect.objectContaining({ type: expect.any(String) }),
      claim_type: expect.any(String),
      citations: [],
      selected: expect.any(Boolean),
      direct: true,
      actionable: false,
      severity: "unknown",
      quality: "high",
    });
    expect(context.snapshot.evidence[0].data.inventory_context).toEqual({
      tab: "os",
      filters: { lifecycle: "supported", search: "windows" },
      sort: { os_name: "asc" },
      offset: 0,
      limit: 50,
    });
    expect(
      context.snapshot.evidence.find((item) => item.selected)?.data.selected,
    ).toBe(true);
    expect(context.uncertainty).toEqual([
      "visible subset is incomplete",
      "arc freshness is partial",
    ]);
    expect(context.starterQuestions[0]).toMatchObject({
      specialistId: "inventory_data_health",
      tool: "inventory_resources",
      toolArguments: {},
    });
  });

  it("retains at most 50 inventory rows and reports exact truncation", () => {
    const records = Array.from({ length: 51 }, (_, index) => ({
      identity: `Windows Server|20${String(index).padStart(2, "0")}`,
      kind: "os_group" as const,
      source: "inventory/os_observations",
      data: {
        os_name: "Windows Server",
        os_version: `20${String(index).padStart(2, "0")}`,
        machine_count: 1,
        source_types: ["azure_vm"],
        lifecycle_status: "Supported",
        support_end: "2034-11-14",
        days_remaining: 2981,
        review_required: false,
      },
    }));

    const context = buildInventoryCopilotContext({
      ...baseInput,
      records,
      selectedIdentity: null,
      totalCount: 51,
      limit: 100,
    });

    expect(context.snapshot.evidence).toHaveLength(50);
    expect(context.snapshot.coverage).toEqual({
      visible_count: 50,
      total_count: 51,
      complete: false,
    });
    expect(context.uncertainty).toContain(
      "evidence retention omitted 1 inventory row",
    );
  });

  it("emits discriminated canonical Azure and non-Azure entities", () => {
    const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
    const domain = snapshot.evidence.find(
      (item) => item.source === "inventory/os_observations",
    );
    const azure = snapshot.evidence.find(
      (item) => item.source === "inventory/resource_observations",
    );

    expect(domain?.entity).toEqual({
      type: "domain",
      namespace: "inventory",
      kind: "os_group",
      source_key: "Windows Server|2019",
    });
    expect(domain?.resource_id).toBe("");
    expect(azure?.entity).toEqual({
      type: "azure",
      resource_id:
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.app/containerapps/app-1",
    });
    expect(azure?.resource_id).toBe(
      "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.app/containerapps/app-1",
    );
  });

  it("matches the backend stable evidence key algorithm", () => {
    expect(
      canonicalEvidenceStableId({
        source: "inventory/os_observations",
        sourceKey: "Windows Server|2019",
        entity: {
          type: "domain",
          namespace: "inventory",
          kind: "os_group",
          source_key: "Windows Server|2019",
        },
        claimType: "os_group",
      }),
    ).toBe("evidence:8260f36a5239818a9fbe280261d162e5");
    expect(
      canonicalEvidenceStableId({
        source: "inventory/os_observations",
        sourceKey: "Straße",
        entity: {
          type: "domain",
          namespace: "inventory",
          kind: "os_group",
          source_key: "Straße",
        },
        claimType: "os_group",
      }),
    ).toBe("evidence:5a5a89948c9154eb1044111a3cc48a88");
    expect(
      canonicalEvidenceStableId({
        source: "inventory/resource_observations",
        sourceKey: "ẞ",
        entity: {
          type: "azure",
          resource_id:
            "/subscriptions/SUB-A/resourceGroups/Straße/providers/Microsoft.Test/widgets/ẞ",
        },
        claimType: "azure_group",
      }),
    ).toBe("evidence:691f8afa04ab5d7e4dd94f41aade18e1");
  });

  it("keeps stable keys and serialization unchanged across reorder and refresh", () => {
    const first = buildInventoryCopilotContext(baseInput);
    const reordered = buildInventoryCopilotContext({
      ...baseInput,
      records: [...records]
        .reverse()
        .map((record) => ({
          ...record,
          observedAt: "2026-09-06T10:00:00Z",
        })),
      sourceStatuses: [...baseInput.sourceStatuses].reverse(),
    });

    expect(first.snapshot.evidence.map((item) => item.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((item) => item.evidence_id),
    );
    expect(first.snapshot.evidence.map((item) => item.source_key)).toEqual(
      reordered.snapshot.evidence.map((item) => item.source_key),
    );
    const withoutObservationTimes = (value: string) =>
      value.replaceAll(/2026-(08-25|09-06)T\d{2}:00:00Z/g, "OBSERVED");
    expect(
      withoutObservationTimes(serializeCopilotSnapshot(first.snapshot)),
    ).toBe(
      withoutObservationTimes(serializeCopilotSnapshot(reordered.snapshot)),
    );
  });

  it("preserves pagination mismatch and unavailable source uncertainty", () => {
    const context = buildInventoryCopilotContext({
      ...baseInput,
      records: records.slice(0, 1),
      totalCount: 20,
      offset: 10,
      limit: 10,
      sourceStatuses: [
        {
          source: "arc",
          status: "unavailable",
        },
      ],
    });

    expect(context.snapshot.coverage).toEqual({
      visible_count: 1,
      total_count: 20,
      complete: false,
    });
    expect(context.snapshot.freshness).toEqual([
      {
        source: "inventory/os_observations",
        observed_at: "unknown",
        status: "unavailable",
      },
    ]);
    expect(context.uncertainty).toEqual([
      "visible subset is incomplete",
      "arc freshness is unavailable",
    ]);
  });

  it("serializes object keys deterministically regardless of insertion order", () => {
    const left = buildInventoryCopilotContext({
      ...baseInput,
      records: [{
        ...records[0],
        data: { zed: 1, "éclair": 2, alpha: 3 },
      }],
      totalCount: 1,
    }).snapshot;
    const right = buildInventoryCopilotContext({
      ...baseInput,
      records: [{
        ...records[0],
        data: { alpha: 3, "éclair": 2, zed: 1 },
      }],
      totalCount: 1,
    }).snapshot;

    expect(serializeCopilotSnapshot(left)).toBe(serializeCopilotSnapshot(right));
  });

  it("preserves contradictory values as stable conflict variants", () => {
    const conflicting = [
      {
        ...records[0],
        data: { ...records[0].data, lifecycle_status: "supported" },
      },
      {
        ...records[0],
        data: { ...records[0].data, lifecycle_status: "unsupported" },
      },
    ];

    const snapshot = buildInventoryCopilotContext({
      ...baseInput,
      records: conflicting,
      totalCount: conflicting.length,
    }).snapshot;

    expect(snapshot.evidence).toHaveLength(2);
    expect(new Set(snapshot.evidence.map((item) => item.evidence_id)).size).toBe(
      2,
    );
    expect(new Set(snapshot.evidence.map((item) => item.source_key))).toEqual(
      new Set(["Windows Server|2019"]),
    );
    expect(new Set(snapshot.evidence.map((item) => item.claim_type))).toEqual(
      new Set(["os_group"]),
    );
    expect(
      snapshot.evidence.filter((item) => item.data.selected === true),
    ).toHaveLength(1);
  });

  it("retains bounded filter context when the visible page is empty", () => {
    const snapshot = buildInventoryCopilotContext({
      ...baseInput,
      records: [],
      totalCount: 0,
    }).snapshot;

    expect(snapshot.coverage).toEqual({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(snapshot.evidence).toHaveLength(1);
    expect(snapshot.evidence[0]).toMatchObject({
      source: "inventory/os_observations",
      status: "empty",
      claim_type: "page_context",
      data: {
        inventory_context: {
          filters: { lifecycle: "supported", search: "windows" },
          sort: { os_name: "asc" },
          offset: 0,
          limit: 50,
        },
        mutation_authorized: false,
        selected: false,
      },
    });
  });

  it("keeps a filtered-empty page partial against its server total", () => {
    const context = buildInventoryCopilotContext({
      ...baseInput,
      records: [],
      totalCount: 2,
    });

    expect(context.snapshot.coverage).toEqual({
      visible_count: 0,
      total_count: 2,
      complete: false,
    });
    expect(context.snapshot.evidence).toHaveLength(1);
    expect(context.snapshot.evidence[0].data.mutation_authorized).toBe(false);
    expect(context.uncertainty).toContain("visible subset is incomplete");
  });

  it("merges exact duplicates independently of input order", () => {
    const duplicate = {
      ...records[0],
      status: "denied" as const,
      observedAt: "2026-08-25T09:00:00Z",
    };
    const stronger = {
      ...records[0],
      status: "ok" as const,
      observedAt: "2026-08-25T10:00:00Z",
    };
    const build = (items: InventoryCopilotRecord[]) =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: items,
        totalCount: 1,
      }).snapshot.evidence;

    expect(build([duplicate, stronger])).toEqual(build([stronger, duplicate]));
    expect(build([duplicate, stronger])).toMatchObject([
      {
        status: "denied",
        observed_at: "2026-08-25T10:00:00Z",
      },
    ]);

    const uppercase = {
      ...records[0],
      identity: "KEY",
      source: "INVENTORY/OS_OBSERVATIONS",
      data: { value: true },
    };
    const lowercase = {
      ...records[0],
      identity: "key",
      source: "inventory/os_observations",
      data: { value: true },
    };
    const buildCaseVariants = (items: InventoryCopilotRecord[]) =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: items,
        selectedIdentity: "KEY",
        totalCount: 1,
      }).snapshot.evidence;

    expect(buildCaseVariants([uppercase, lowercase])).toEqual(
      buildCaseVariants([lowercase, uppercase]),
    );
    expect(buildCaseVariants([uppercase, lowercase])).toMatchObject([
      { selected: true, data: { selected: true } },
    ]);
  });

  it("rejects invalid coverage and every server-side size bound", () => {
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        totalCount: 1,
      }),
    ).toThrow(/visible count cannot exceed total count/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: Array.from(
          { length: COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1 },
          (_, index) => ({
            ...records[0],
            identity: `row-${index}`,
          }),
        ),
        totalCount: COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1,
      }),
    ).toThrow(/evidence rows/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [
          {
            ...records[0],
            data: {
              blob: "x".repeat(
                COPILOT_SNAPSHOT_LIMITS.evidenceRowBytes + 1,
              ),
            },
          },
        ],
        totalCount: 1,
      }),
    ).toThrow(/evidence row/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [
          {
            ...records[0],
            data: { values: Array.from({ length: 1_500 }, () => 1e-7) },
          },
        ],
        totalCount: 1,
      }),
    ).toThrow(/evidence row/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        sourceStatuses: Array.from(
          { length: COPILOT_SNAPSHOT_LIMITS.freshnessRecords + 1 },
          (_, index) => ({
            source: `source-${index}`,
            observedAt: "2026-08-25T10:00:00Z",
            status: "fresh",
          }),
        ),
      }),
    ).toThrow(/freshness records/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{ ...records[0], source: "x".repeat(129) }],
      }),
    ).toThrow(/evidence source/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{ ...records[0], identity: "x".repeat(257) }],
      }),
    ).toThrow(/source key/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: Object.fromEntries(
          Array.from({ length: 17 }, (_, index) => [`filter-${index}`, "value"]),
        ),
      }),
    ).toThrow(/inventory filters/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: { search: "x".repeat(161) },
      }),
    ).toThrow(/inventory selector filter search/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{
          ...records[0],
          data: {
            ...records[0].data,
            os_name: "x".repeat(121),
          },
        }],
      }),
    ).toThrow(/inventory selector os_name/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: {
          os_name: "x".repeat(117),
          os_version: "y".repeat(117),
        },
      }),
    ).toThrow(/resource selector/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        tab: "azure",
        records: [{
          ...records[1],
          data: {
            resource_type: `microsoft.test/${"x".repeat(100)}`,
            sku: "s".repeat(60),
            tier: "t".repeat(60),
          },
        }],
        selectedIdentity: "vm-1",
        totalCount: 1,
      }),
    ).toThrow(/resource selector/i);
  });
});

describe("connections, Fabric medallion, and governance Copilot page adapters", () => {
  type CoreContext = ReturnType<typeof buildConnectionsCopilotContext>;
  const rowByClaim = (ctx: CoreContext, claim: string) =>
    ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

  const connectionsInput = {
    scope: { subscription: ["sub-a"] },
    connections: [
      {
        connection_id: "prod",
        name: "Production",
        subscription_id: "00000000-0000-0000-0000-000000000001",
        business_service: "Payments",
        environment: "prod",
        criticality: "critical",
        health_status: "healthy",
        sync_status: "succeeded",
        sync_record_count: 12700,
        last_successful_sync_at: "2026-09-07T10:00:00Z",
        is_active: true,
      },
      {
        connection_id: "staging",
        name: "Staging",
        subscription_id: "00000000-0000-0000-0000-000000000002",
        business_service: "Payments",
        environment: "staging",
        criticality: "standard",
        health_status: "degraded",
        sync_status: "failed",
        sync_record_count: 0,
        last_successful_sync_at: null,
        is_active: true,
      },
    ],
    loadedCount: 2,
    totalCount: 5,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    selectedConnectionId: "prod",
    filters: { view: ["subscriptions"], page: ["1"] },
    evidence: [
      {
        source_engine: "onboarding.SubscriptionOnboardingService",
        source_table: "connection_registry",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds connection source identities, capacity, deployment-blocked state, coverage, and inventory hints", () => {
    const context = buildConnectionsCopilotContext(connectionsInput);
    const reordered = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [...connectionsInput.connections].reverse(),
    });

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "connections",
    });
    // Each connection is a stable non-ARM source identity, never leaked into a
    // scope-validated Azure resource field.
    const selected = rowByClaim(context, "subscription_connection").find(
      (row) => row.data.connection_id === "prod",
    );
    expect(selected?.resource_id).toBeUndefined();
    expect(selected?.data).toMatchObject({
      entity: {
        type: "observation",
        source: "connections/registry",
        source_key: "prod",
      },
      health_status: "healthy",
      sync_status: "succeeded",
      record_count: 12700,
      deployment_blocked: false,
      selected: true,
      actionable: false,
      mutation_authorized: false,
    });
    // A failed sync is a distinct deployment-blocked state.
    const blocked = rowByClaim(context, "subscription_connection").find(
      (row) => row.data.connection_id === "staging",
    );
    expect(blocked?.data.deployment_blocked).toBe(true);
    expect(context.coverage.connections).toMatchObject({
      visible_count: 2,
      total_count: 5,
      complete: false,
      truncated: true,
    });
    // Deterministic identities regardless of input order.
    expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((row) => row.evidence_id),
    );
    // Inventory & Data Health hints stay exact manifest IDs and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "inventory_data_health"
      && starter.tool === "inventory_resources")).toBe(true);
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    expect(context.snapshot.freshness).toContainEqual(
      expect.objectContaining({ source: "connections/registry", status: "fresh" }),
    );
    expect(context.snapshot.freshness).toContainEqual(
      expect.objectContaining({ source: "coverage", status: "fresh" }),
    );
    expect(context.snapshot.freshness).toContainEqual(
      expect.objectContaining({
        source: "onboarding.SubscriptionOnboardingService/connection_registry",
        status: "fresh",
      }),
    );
  });

  it("distinguishes a healthy-empty connection registry from an unavailable one", () => {
    const healthyEmpty = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [],
      loadedCount: 0,
      totalCount: 0,
      selectedConnectionId: null,
      available: true,
      freshness: "fresh" as const,
    });
    expect(healthyEmpty.coverage.connections).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
      truncated: false,
    });
    expect(healthyEmpty.uncertainty).not.toEqual(
      expect.arrayContaining(["connections freshness is unavailable"]),
    );

    const unavailable = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [],
      loadedCount: 0,
      totalCount: 0,
      selectedConnectionId: null,
      available: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.coverage.connections.complete).toBe(false);
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["connections/registry freshness is unavailable"]),
    );
  });

  const fabricInput = {
    scope: { subscription: ["sub-a"] },
    subscriptionId: "00000000-0000-0000-0000-000000000001",
    layers: [
      { layer: "bronze" as const, healthy: 4, total: 4 },
      { layer: "silver" as const, healthy: 2, total: 3 },
      { layer: "gold" as const, healthy: 0, total: 0 },
    ],
    manifest: [
      {
        projection_name: "inventory_gold",
        disposition: "active",
        compatibility_version: "v2",
        subscription_id: "00000000-0000-0000-0000-000000000001",
      },
    ],
    manifestTotalCount: 3,
    governance: {
      ownership_gap_count: 2,
      tag_gap_count: 1,
      referential_integrity_blockers: 0,
    },
    capacity: { status: "active", state: "Active", capacity_name: "cap-1" },
    semanticReadiness: { status: "ready" },
    dataAgentReadiness: { status: "not_configured", configured: false },
    lineageRef: "fabric://lineage/inventory",
    available: true,
    deploymentBlocked: false,
    freshness: "partial" as const,
    observedAt: "2026-09-07T09:30:00Z",
    evidence: [
      {
        source_engine: "fabric.medallion_health",
        source_table: "metadata_source_status",
        timestamp: "2026-09-07T09:30:00Z",
        confidence: "medium" as const,
        freshness: "aging" as const,
      },
      {
        source_engine: "ontology.publication_manifest",
        source_table: "metadata_publication_manifest",
        timestamp: "2026-09-01T16:15:42Z",
        confidence: "high" as const,
        freshness: "stale" as const,
      },
    ],
    sourceStatuses: [
      { source: "fabric/medallion-layers", freshness: "aging", observedAt: "2026-09-07T09:30:00Z" },
      { source: "fabric/manifest", freshness: "stale", observedAt: "2026-09-01T16:15:42Z" },
      { source: "fabric/governance", freshness: "fresh", observedAt: "2026-09-07T09:30:00Z" },
      { source: "fabric/capabilities", freshness: "fresh", observedAt: "2026-09-07T09:30:00Z" },
    ],
  };

  it("binds medallion layer, manifest, governance, and readiness evidence with partial freshness", () => {
    const context = buildFabricMedallionCopilotContext(fabricInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "fabric-medallion",
    });
    const silver = rowByClaim(context, "medallion_layer").find(
      (row) => row.data.layer === "silver",
    );
    expect(silver?.data).toMatchObject({
      entity: { type: "observation", source: "fabric/medallion-layers", source_key: "silver" },
      healthy: 2,
      total: 3,
      actionable: false,
      mutation_authorized: false,
    });
    expect(silver?.observed_at).toBe("2026-09-07T09:30:00Z");
    // Gold layer is healthy-empty (0/0), never an outage.
    const gold = rowByClaim(context, "medallion_layer").find((row) => row.data.layer === "gold");
    expect(gold?.data).toMatchObject({ healthy: 0, total: 0 });
    expect(rowByClaim(context, "fabric_manifest").length).toBe(1);
    expect(rowByClaim(context, "fabric_manifest")[0]).toMatchObject({
      observed_at: "2026-09-01T16:15:42Z",
      data: {
        entity: {
          type: "observation",
          source: "fabric/manifest",
          source_key: "inventory_gold",
        },
      },
    });
    expect(rowByClaim(context, "fabric_governance")[0]?.data).toMatchObject({
      ownership_gap_count: 2,
      tag_gap_count: 1,
      referential_integrity_blockers: 0,
    });
    expect(rowByClaim(context, "fabric_capacity")[0]?.data).toMatchObject({
      status: "active",
      data_agent_configured: false,
    });
    expect(context.coverage.manifest).toMatchObject({
      visible_count: 1,
      total_count: 3,
      truncated: true,
    });
    // Partial freshness is surfaced as uncertainty, not hidden.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "fabric/medallion-layers freshness is partial",
        "fabric/manifest freshness is stale",
      ]),
    );
    expect(context.snapshot.freshness).toEqual(expect.arrayContaining([
      {
        source: "fabric/medallion-layers",
        observed_at: "2026-09-07T09:30:00Z",
        status: "partial",
      },
      {
        source: "fabric/manifest",
        observed_at: "2026-09-01T16:15:42Z",
        status: "stale",
      },
      {
        source: "coverage",
        observed_at: "2026-09-01T16:15:42Z",
        status: "stale",
      },
      {
        source: "fabric.medallion_health/metadata_source_status",
        observed_at: "2026-09-07T09:30:00Z",
        status: "partial",
      },
      {
        source: "ontology.publication_manifest/metadata_publication_manifest",
        observed_at: "2026-09-01T16:15:42Z",
        status: "stale",
      },
    ]));
    expect(context.snapshot.evidence).toEqual(expect.arrayContaining([
      expect.objectContaining({
        section: "ontology.publication_manifest/metadata_publication_manifest",
        observed_at: "2026-09-01T16:15:42Z",
      }),
    ]));
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "inventory_data_health"
      && starter.tool === "inventory_resources")).toBe(true);
  });

  it("keeps deployment-blocked capacity distinct from an unavailable Fabric provider", () => {
    const blocked = buildFabricMedallionCopilotContext({
      ...fabricInput,
      layers: [
        { layer: "bronze" as const, healthy: 0, total: 0 },
        { layer: "silver" as const, healthy: 0, total: 0 },
        { layer: "gold" as const, healthy: 0, total: 0 },
      ],
      capacity: { status: "paused", state: "Paused", capacity_name: "cap-1" },
      deploymentBlocked: true,
      available: true,
      freshness: "fresh" as const,
      sourceStatuses: [
        { source: "fabric/capabilities", availability: "blocked", freshness: "unknown" },
      ],
    });
    expect(blocked.uncertainty).toEqual(
      expect.arrayContaining(["fabric_medallion is deployment-blocked"]),
    );
    expect(rowByClaim(blocked, "fabric_capacity")[0]?.data.deployment_blocked).toBe(true);

    const unavailable = buildFabricMedallionCopilotContext({
      ...fabricInput,
      layers: [],
      manifest: [],
      manifestTotalCount: 0,
      governance: null,
      capacity: null,
      semanticReadiness: null,
      dataAgentReadiness: null,
      available: false,
      deploymentBlocked: false,
      freshness: "unavailable" as const,
      sourceStatuses: [
        { source: "fabric/medallion-layers", availability: "unavailable", freshness: "unknown" },
      ],
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["fabric/medallion-layers freshness is unavailable"]),
    );
    expect(unavailable.uncertainty).not.toEqual(
      expect.arrayContaining(["fabric_medallion is deployment-blocked"]),
    );
  });

  it("reports retained-manifest coverage honestly beyond the evidence-row bound", () => {
    const manifest = Array.from({ length: 205 }, (_, index) => ({
      projection_name: `projection_${index}`,
      disposition: "active",
      compatibility_version: "v2",
      subscription_id: "00000000-0000-0000-0000-000000000001",
    }));
    const context = buildFabricMedallionCopilotContext({
      ...fabricInput,
      manifest,
      manifestTotalCount: manifest.length,
    });

    expect(context.coverage.manifest).toMatchObject({
      visible_count: 205,
      total_count: 205,
      complete: false,
      truncated: true,
    });
    expect(rowByClaim(context, "fabric_manifest").length).toBeLessThan(205);
    expect(context.uncertainty).toEqual(expect.arrayContaining([
      "manifest coverage is truncated",
      expect.stringMatching(/^evidence retention omitted \d+ rows$/),
    ]));
  });

  const governanceInput = {
    scope: { subscription: ["sub-a"] },
    roles: [
      { role_id: "operator", name: "Operator", permissions: ["read"] },
      { role_id: "admin", name: "Administrator", permissions: ["admin", "read"] },
    ],
    rolesTotalCount: 4,
    policies: [
      { section: "onboarding_policy", setting_count: 3 },
      { section: "retention_policy", setting_count: 2 },
    ],
    accessReviewAudiences: ["security", "finance"],
    auditExportKinds: ["identity", "exposure"],
    settingsAvailable: true,
    audiencesAvailable: true,
    kindsAvailable: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    evidence: [
      {
        source_engine: "Governance",
        source_table: "enterprise_settings",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds governance roles, policies, audiences, and export kinds with bounded totals", () => {
    const context = buildGovernanceCopilotContext(governanceInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "governance",
    });
    const adminRole = rowByClaim(context, "governance_role").find(
      (row) => row.data.role_id === "admin",
    );
    expect(adminRole?.data).toMatchObject({
      entity: { type: "observation", source: "governance/settings", source_key: "admin" },
      privileged: true,
      actionable: false,
      mutation_authorized: false,
    });
    expect([
      "governance_role",
      "governance_policy",
      "access_review_audience",
      "audit_export_kind",
    ].every((claim) =>
      rowByClaim(context, claim).every((row) =>
        (row.data.entity as { type: string }).type === "observation"))).toBe(true);
    expect(rowByClaim(context, "governance_policy").length).toBe(2);
    // Access-review audiences are the identity-collaboration evidence.
    expect(rowByClaim(context, "access_review_audience").length).toBe(2);
    expect(rowByClaim(context, "audit_export_kind").length).toBe(2);
    expect(context.coverage.roles).toMatchObject({
      visible_count: 2,
      total_count: 4,
      truncated: true,
    });
    // Governance starters stay within the governance specialist and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "governance"
      && (
        starter.tool === undefined
        || ["business_service_context", "application_context", "risk_context", "impact_context"].includes(starter.tool)
      )
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
  });

  it("treats settings, audiences, and export kinds as independent optional sources", () => {
    const context = buildGovernanceCopilotContext({
      ...governanceInput,
      accessReviewAudiences: [],
      auditExportKinds: [],
      audiencesAvailable: false,
      kindsAvailable: false,
    });
    // Settings remain usable even when review/export enrichment is unavailable.
    expect(rowByClaim(context, "governance_role").length).toBe(2);
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "access_reviews freshness is unavailable",
        "audit_exports freshness is unavailable",
      ]),
    );
    expect(context.uncertainty).not.toEqual(
      expect.arrayContaining(["settings freshness is unavailable"]),
    );
  });
});

describe("identity, FinOps, and resource-health Copilot page adapters", () => {
  type CoreContext = ReturnType<typeof buildIdentityCopilotContext>;
  const rowByClaim = (ctx: CoreContext, claim: string) =>
    ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

  const identityInput = {
    scope: { subscription: ["sub-a"] },
    summary: {
      principal_count: 42,
      privileged_principal_count: 3,
      stale_assignment_count: 5,
      non_human_principal_count: 8,
      assignment_count: 120,
    },
    principals: [
      {
        principal_id: "11111111-1111-1111-1111-111111111111",
        principal_type: "User",
        privileged: true,
        stale: false,
        widest_scope_breadth: "subscription",
        assignment_count: 6,
        roles: ["Owner", "Contributor"],
      },
      {
        principal_id: "22222222-2222-2222-2222-222222222222",
        principal_type: "ServicePrincipal",
        privileged: false,
        stale: true,
        widest_scope_breadth: "resource_group",
        assignment_count: 1,
        roles: ["Reader"],
      },
    ],
    principalsTotalCount: 42,
    owners: [
      {
        principal_id: "33333333-3333-3333-3333-333333333333",
        principal_type: "User",
        subscription_id: "00000000-0000-0000-0000-000000000001",
        scope_breadth: "subscription",
        stale: false,
      },
    ],
    ownersTotalCount: 1,
    staleAccess: [
      {
        assignment_id: "assign-1",
        principal_id: "22222222-2222-2222-2222-222222222222",
        role: "Reader",
        privileged: false,
      },
    ],
    staleTotalCount: 5,
    spnCredentials: [
      {
        credential_id: "cred-1",
        connection_name: "Production",
        rotation_status: "expiring_soon",
        days_to_expiry: 12,
        issues_count: 1,
      },
    ],
    spnTotalCount: 2,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    selectedPrincipalId: "11111111-1111-1111-1111-111111111111",
    filters: { view: ["principals"] },
    evidence: [
      {
        source_engine: "Governance",
        source_table: "identity_assignments",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds principal, owner, access-review, and SPN evidence as scope-safe observations", () => {
    const context = buildIdentityCopilotContext(identityInput);
    const reordered = buildIdentityCopilotContext({
      ...identityInput,
      principals: [...identityInput.principals].reverse(),
    });

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "identity",
    });
    // Every principal is a non-authoritative observation: the principal id is
    // never leaked into a scope-validated Azure resource field or tool authority.
    const principalRows = rowByClaim(context, "identity_principal");
    expect(principalRows.length).toBe(2);
    expect(principalRows.every((row) => row.resource_id === undefined)).toBe(true);
    expect(principalRows.every((row) =>
      (row.data.entity as { type: string }).type === "observation")).toBe(true);
    const selected = principalRows.find(
      (row) => (row.data.entity as { source_key: string }).source_key
        === "11111111-1111-1111-1111-111111111111",
    );
    expect(selected?.data).toMatchObject({
      entity: {
        type: "observation",
        source: "identity/principals",
        source_key: "11111111-1111-1111-1111-111111111111",
      },
      principal_type: "User",
      privileged: true,
      widest_scope_breadth: "subscription",
      selected: true,
      actionable: false,
      mutation_authorized: false,
    });
    const summaryRows = rowByClaim(context, "identity_summary");
    expect(summaryRows.length).toBe(1);
    expect(summaryRows[0].data).toMatchObject({
      principal_count: 42,
      privileged_principal_count: 3,
      stale_assignment_count: 5,
      assignment_count: 120,
    });
    expect(rowByClaim(context, "subscription_owner").length).toBe(1);
    expect(rowByClaim(context, "stale_access").length).toBe(1);
    expect(rowByClaim(context, "spn_credential").length).toBe(1);
    expect([
      "identity_principal",
      "subscription_owner",
      "stale_access",
      "spn_credential",
    ].every((claim) =>
      rowByClaim(context, claim).every((row) =>
        (row.data.entity as { type: string }).type === "observation"))).toBe(true);
    expect(normalizeCopilotSnapshotV2(context.snapshot).selected_entities).toEqual([]);
    expect(context.coverage.principals).toMatchObject({
      visible_count: 2,
      total_count: 42,
      truncated: true,
    });
    // Deterministic identities regardless of input order.
    expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((row) => row.evidence_id),
    );
    // Identity hints stay within the identity_access specialist and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "identity_access"
      && (
        starter.tool === undefined
        || ["business_service_context", "application_context", "risk_context", "search"].includes(starter.tool)
      )
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
    expectCanonicalEndpointAccepts([{
      name: "Identity without semantic resolution",
      requested_scope: context.requestedScope,
      snapshot: normalizeCopilotSnapshotV2(context.snapshot),
      semantic_available: false,
      expected_claim_types: [
        "identity_principal",
        "subscription_owner",
        "stale_access",
        "spn_credential",
      ],
    }]);
  });

  it("distinguishes an unavailable identity provider from a healthy-empty scope", () => {
    const healthyEmpty = buildIdentityCopilotContext({
      ...identityInput,
      principals: [],
      owners: [],
      staleAccess: [],
      spnCredentials: [],
      principalsTotalCount: 0,
      ownersTotalCount: 0,
      staleTotalCount: 0,
      spnTotalCount: 0,
      selectedPrincipalId: null,
      available: true,
      freshness: "fresh" as const,
    });
    expect(healthyEmpty.coverage.principals).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(healthyEmpty.uncertainty).not.toEqual(
      expect.arrayContaining(["identity freshness is unavailable"]),
    );

    const unavailable = buildIdentityCopilotContext({
      ...identityInput,
      principals: [],
      owners: [],
      staleAccess: [],
      spnCredentials: [],
      principalsTotalCount: 0,
      ownersTotalCount: 0,
      staleTotalCount: 0,
      spnTotalCount: 0,
      selectedPrincipalId: null,
      available: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["identity freshness is unavailable"]),
    );
  });

  const finopsInput = {
    scope: { subscription: ["sub-a"] },
    summary: {
      identified_annual_savings: 125000,
      currency: "USD",
      savings_opportunity_count: 10,
      quantified_opportunity_count: 7,
      waste_item_count: 4,
      actual_spend: 98000,
      actual_spend_currency: "USD",
      actual_spend_period_start: "2026-08-01",
      actual_spend_period_end: "2026-08-31",
      unavailable_metrics: [
        { metric: "forecast_spend", reason: "Cost Management forecast not enabled" },
      ],
    },
    dimension: "business_service",
    attribution: [
      {
        dimension: "business_service",
        group: "Payments",
        identified_annual_savings: 60000,
        savings_opportunity_count: 4,
        waste_item_count: 2,
      },
    ],
    attributionTotalCount: 3,
    opportunities: [
      {
        recommendation_id: "rec-1",
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        problem: "Right-size underused VM",
        impact: "high",
        annual_savings: 24000,
        currency: "USD",
        owner: "team-payments",
        business_service: "Payments",
      },
      {
        recommendation_id: "rec-2",
        problem: "Unquantified recommendation",
        impact: "medium",
        annual_savings: null,
        currency: "USD",
        business_service: "Networking",
      },
    ],
    opportunitiesTotalCount: 10,
    waste: [
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/disks/disk-1",
        resource_type: "Microsoft.Compute/disks",
        reason: "unattached",
        annual_savings: 1200,
        currency: "USD",
        owner: "team-payments",
      },
    ],
    wasteTotalCount: 4,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    evidence: [
      {
        source_engine: "Advisor",
        source_table: "cost_recommendations",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds FinOps attribution, opportunity, and waste with currency, window, totals, and uncertainty", () => {
    const context = buildFinOpsCopilotContext(finopsInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "finops",
    });
    // Cost summary carries currency and observation window.
    const summary = rowByClaim(context, "finops_summary")[0]?.data;
    expect(summary).toMatchObject({
      entity: {
        type: "observation",
        source: "finops/summary",
        source_key: "finops-summary",
      },
      currency: "USD",
      actual_spend_period_start: "2026-08-01",
      actual_spend_period_end: "2026-08-31",
      actionable: false,
      mutation_authorized: false,
    });
    // A quantified opportunity resource is a canonical ARM identity.
    const opportunity = rowByClaim(context, "savings_opportunity").find(
      (row) => row.data.recommendation_id === "rec-1",
    );
    expect(opportunity?.data.entity).toEqual({
      type: "azure",
      resource_id:
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
    });
    // A null saving is preserved as "not quantified", never coerced to zero.
    const unquantified = rowByClaim(context, "savings_opportunity").find(
      (row) => row.data.recommendation_id === "rec-2",
    );
    expect(unquantified?.data.annual_savings).toBeNull();
    expect(unquantified?.data.entity).toMatchObject({
      type: "observation",
      source: "finops/opportunities",
    });
    expect(rowByClaim(context, "cost_attribution")).toHaveLength(1);
    expect(rowByClaim(context, "cost_attribution")[0]?.data.entity).toMatchObject({
      type: "observation",
      source: "finops/attribution",
    });
    expect(rowByClaim(context, "waste_item").length).toBe(1);
    expect(context.coverage.opportunities).toMatchObject({
      visible_count: 2,
      total_count: 10,
      truncated: true,
    });
    // Genuinely unavailable metrics are surfaced as uncertainty.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining(["forecast_spend is unavailable: Cost Management forecast not enabled"]),
    );
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "finops"
      && (
        starter.tool === undefined
        || ["business_service_context", "application_context", "risk_context", "search"].includes(starter.tool)
      )
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
    expectCanonicalEndpointAccepts([{
      name: "FinOps without semantic resolution",
      requested_scope: context.requestedScope,
      snapshot: normalizeCopilotSnapshotV2(context.snapshot),
      semantic_available: false,
      expected_claim_types: [
        "finops_summary",
        "cost_attribution",
        "savings_opportunity",
        "waste_item",
      ],
    }]);
  });

  const healthInput = {
    scope: { subscription: ["sub-a"] },
    resources: [
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        resource_name: "vm-1",
        resource_type: "Microsoft.Compute/virtualMachines",
        status: "critical",
        cpu_percent: 94.2,
        memory_percent: null,
        disk_free_percent: null,
        observed_at: "2026-09-07T10:00:00Z",
        unavailable_metrics: ["memory_percent", "disk_free_percent"],
        series_point_count: 12,
      },
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.HybridCompute/machines/arc-1",
        resource_name: "arc-1",
        resource_type: "Microsoft.HybridCompute/machines",
        status: "healthy",
        cpu_percent: 21.0,
        memory_percent: 40.0,
        disk_free_percent: 55.0,
        observed_at: "2026-09-07T10:00:00Z",
        unavailable_metrics: [],
        series_point_count: 12,
      },
    ],
    loadedCount: 2,
    totalCount: 2,
    summary: { total: 2, critical: 1, warning: 0, healthy: 1, unknown: 0 },
    available: true,
    cached: true,
    observedAt: "2026-09-07T10:00:00Z",
    freshness: "fresh" as const,
    unavailableMetrics: ["memory_percent", "disk_free_percent"],
    warnings: ["No Log Analytics workspace discovered for guest counters"],
    selectedResourceId:
      "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
    evidence: [
      {
        source_engine: "AzureMonitor",
        source_table: "resource_metrics",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds resource-health identities, observation windows, and missing-series status", () => {
    const context = buildResourceHealthCopilotContext(healthInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "resource-health",
    });
    expect(normalizeCopilotSnapshotV2(context.snapshot).page_kind).toBe(
      "resource_health",
    );
    // Each resource is a canonical ARM identity.
    const resourceRows = rowByClaim(context, "resource_utilization");
    expect(resourceRows.length).toBe(2);
    const selected = context.snapshot.evidence.find(
      (row) => row.resource_id ===
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
    );
    expect(selected?.data).toMatchObject({
      claim_type: "resource_utilization",
      status: "critical",
      series_point_count: 12,
      actionable: false,
      mutation_authorized: false,
    });
    // Missing series/metrics are stated, never fabricated as zero.
    expect(selected?.data.unavailable_metrics).toEqual(["memory_percent", "disk_free_percent"]);
    expect(rowByClaim(context, "resource_metric_coverage")).toEqual([
      expect.objectContaining({
        data: expect.objectContaining({
          unavailable_metrics: ["memory_percent", "disk_free_percent"],
          warnings: ["No Log Analytics workspace discovered for guest counters"],
          cached: true,
          mutation_authorized: false,
        }),
      }),
    ]);
    expect(context.coverage.resources).toMatchObject({
      visible_count: 2,
      total_count: 2,
      complete: true,
    });
    // Page-level missing metrics surface as uncertainty.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "memory_percent series is unavailable",
        "disk_free_percent series is unavailable",
      ]),
    );
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "resource_health_observability"
      && (
        starter.tool === undefined
        || ["incidents", "impact_context", "search"].includes(starter.tool)
      )
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
    expect(context.starterQuestions).toEqual([
      expect.objectContaining({
        label: "What incidents relate to these resources?",
        tool: "incidents",
        toolArguments: {},
      }),
      expect.objectContaining({
        label: "Which services are impacted by resource pressure?",
        tool: "search",
        toolArguments: { query: "resource pressure service impact" },
      }),
      expect.objectContaining({
        label: "Search resource utilization anomalies.",
        tool: "search",
        toolArguments: { query: "resource utilization anomalies" },
      }),
    ]);
    expect(context.snapshot.freshness).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "coverage", status: "fresh" }),
      expect.objectContaining({ source: "resource_health", status: "fresh" }),
      expect.objectContaining({ source: "resource-health/metrics", status: "fresh" }),
      expect.objectContaining({
        source: "AzureMonitor/resource_metrics",
        status: "fresh",
      }),
    ]));
  });

  it("keeps an unavailable resource-health provider distinct from an empty scope", () => {
    const unavailable = buildResourceHealthCopilotContext({
      ...healthInput,
      resources: [],
      loadedCount: 0,
      totalCount: 0,
      summary: { total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0 },
      unavailableMetrics: [],
      warnings: [],
      selectedResourceId: null,
      available: false,
      cached: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["resource_health freshness is unavailable"]),
    );

    const empty = buildResourceHealthCopilotContext({
      ...healthInput,
      resources: [],
      loadedCount: 0,
      totalCount: 0,
      summary: { total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0 },
      unavailableMetrics: [],
      warnings: [],
      selectedResourceId: null,
      available: true,
      cached: false,
      freshness: "fresh" as const,
    });
    expect(empty.coverage.resources).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(empty.uncertainty).not.toEqual(
      expect.arrayContaining(["resource_health freshness is unavailable"]),
    );
  });

  it("marks retained Resource Health evidence partial above the 50-resource bound", () => {
    const resources = Array.from({ length: 51 }, (_, index) => ({
      ...healthInput.resources[0],
      resource_id:
        `/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-${index}`,
      resource_name: `vm-${index}`,
    }));

    const context = buildResourceHealthCopilotContext({
      ...healthInput,
      resources,
      loadedCount: resources.length,
      totalCount: resources.length,
      selectedResourceId: null,
    });

    expect(context.coverage.resources).toMatchObject({
      visible_count: 50,
      total_count: 51,
      complete: false,
      truncated: true,
    });
    expect(context.uncertainty).toContain("resources coverage is truncated");
    expect(context.snapshot.evidence.filter(
      (row) => row.data.claim_type === "resource_utilization",
    )).toHaveLength(50);
    expect(context.snapshot.evidence.length).toBeLessThanOrEqual(200);
  });
});

describe("situation detail and service Copilot page adapters", () => {
  const situationDetailInput = {
    scope: { subscription: ["sub-a"] },
    situationId: "situation://one",
    situation: {
      situation_id: "situation://one",
      title: "Database exposure",
      severity: "high",
      priority: "P2",
      lifecycle_state: "open",
      situation_type: "exposure",
      owner: "Security",
      support_team: "Platform",
      evidence_state: "contradictory",
      affected_resource_ids: [
        "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
      ],
      unknowns: ["Service ownership is not known."],
      started_at: "2026-08-25T01:00:00Z",
      last_observed_at: "2026-08-25T01:05:00Z",
    },
    evidence: [
      {
        evidence_id: "evidence://one",
        source_family: "defender",
        source_object_id: "defender-1",
        assertion: "Database exposure detected",
        quality: "contradictory",
        availability: "available",
        freshness: "fresh",
        observed_at: "2026-08-25T01:00:00Z",
        resource_ids: [
          "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
        ],
      },
    ],
    links: [
      {
        link_id: "link://one",
        entity_type: "Exposure",
        entity_id: "exposure-1",
        relation: "relates_to",
        quality: "unresolved",
      },
    ],
    sourceStatuses: [
      { source_family: "defender", availability: "available", freshness: "fresh", observed_at: "2026-08-25T01:00:00Z" },
      { source_family: "policy", availability: "unavailable", freshness: "unknown", observed_at: "" },
    ],
    auditEvents: [
      { event_id: "audit://one", actor: "system:ingestion", action: "evidence.ingested", timestamp: "2026-08-25T01:05:00Z" },
    ],
    auditAvailable: true,
    available: true,
    observedAt: "2026-08-25T01:05:00Z",
    citations: [
      {
        source_engine: "Fabric",
        source_table: "situations",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds situation identity, timeline, evidence trust, affected resources, and links", () => {
    const context = buildSituationDetailCopilotContext(situationDetailInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "incident",
      page_id: "situation:situation://one",
    });
    expect(context.selectedEntities).toEqual([
      {
        type: "domain",
        namespace: "operations",
        kind: "situation",
        source_key: "situation://one",
      },
    ]);
    // Affected resource is retained as a canonical (normalized) ARM entity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.sql/servers/db")).toBe(true);
    // Evidence source trust is retained per row.
    expect(context.snapshot.evidence.some((row) =>
      row.data.source_family === "defender" && row.data.quality === "contradictory")).toBe(true);
    // Every row is forced non-actionable / non-mutation-authorized.
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    expect(context.coverage.evidence).toMatchObject({ visible_count: 1, complete: true });
    expect(context.coverage.links).toMatchObject({ visible_count: 1 });
    expect(context.starterQuestions.length).toBeGreaterThan(0);
    expect(context.starterQuestions.every((q) => q.specialistId === "incident")).toBe(true);
  });

  it("keeps an unavailable source distinct from a fresh source and retains stale freshness", () => {
    const context = buildSituationDetailCopilotContext(situationDetailInput);
    expect(context.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "defender", status: "fresh" }),
        expect.objectContaining({ source: "policy", status: "unavailable" }),
      ]),
    );
  });

  it("distinguishes an unavailable situation record from an authorized empty detail", () => {
    const unavailable = buildSituationDetailCopilotContext({
      ...situationDetailInput,
      situation: null,
      evidence: [],
      links: [],
      auditEvents: [],
      available: false,
      citations: [],
    });
    expect(unavailable.coverage.evidence).toMatchObject({ visible_count: 0, complete: false });
  });

  const servicesInput = {
    scope: { subscription: ["sub-a"] },
    services: [
      {
        name: "Payments",
        environments: ["prod"],
        subscriptionCount: 2,
        situationCount: 3,
        criticalCount: 1,
        healthRisk: 2,
        operationalState: "Critical attention",
      },
      {
        name: "Billing",
        environments: ["prod", "staging"],
        subscriptionCount: 1,
        situationCount: 0,
        criticalCount: 0,
        healthRisk: 0,
        operationalState: "No active situation",
      },
    ],
    visibleCount: 2,
    totalCount: 5,
    filters: { state: ["Critical attention"] },
    connectionsAvailable: true,
    incidentsAvailable: true,
    connectionsObservedAt: "2026-08-25T01:00:00Z",
    incidentsObservedAt: "2026-08-25T01:00:00Z",
    connectionsFreshness: "fresh" as const,
    incidentsFreshness: "fresh" as const,
    evidence: [
      {
        source_engine: "connections",
        source_table: "subscription_connections",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds visible services with ownership/health facts, filters, and honest total coverage", () => {
    const context = buildServicesCopilotContext(servicesInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "services",
      filters: { state: ["Critical attention"] },
    });
    expect(context.snapshot.evidence.some((row) =>
      row.data.service === "Payments" && row.data.situation_count === 3 && row.data.critical_count === 1)).toBe(true);
    expect(context.coverage.services).toMatchObject({
      visible_count: 2,
      total_count: 5,
      complete: false,
      truncated: true,
    });
    expect(context.starterQuestions.every((q) => q.specialistId === "resource_health_observability")).toBe(true);
  });

  it("keeps an unavailable services catalog distinct from an authorized empty catalog", () => {
    const unavailable = buildServicesCopilotContext({
      ...servicesInput,
      services: [],
      visibleCount: 0,
      totalCount: 0,
      connectionsAvailable: false,
      incidentsAvailable: false,
      evidence: [],
    });
    const empty = buildServicesCopilotContext({
      ...servicesInput,
      services: [],
      visibleCount: 0,
      totalCount: 0,
      evidence: [],
    });
    expect(unavailable.coverage.services.complete).toBe(false);
    expect(empty.coverage.services.complete).toBe(true);
    expect(unavailable.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "connections", status: "unavailable" }),
      ]),
    );
  });

  it("withholds unavailable incident counts and separates an unmapped bucket from an identically named real service", () => {
    const context = buildServicesCopilotContext({
      ...servicesInput,
      incidentsAvailable: false,
      services: [
        { ...servicesInput.services[0], id: "unmapped", name: "Unmapped service", operationalState: "Incident evidence unavailable" },
        { ...servicesInput.services[0], id: "service:Unmapped service", name: "Unmapped service", operationalState: "Incident evidence unavailable" },
      ],
    });
    const rows = context.snapshot.evidence.filter(row => row.data.service === "Unmapped service");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.data.situation_count).toBeUndefined();
      expect(row.data.critical_count).toBeUndefined();
      expect(row.data.operational_state).toBe("Incident evidence unavailable");
    }
    expect(context.snapshot.freshness).toEqual(expect.arrayContaining([expect.objectContaining({ source: "incidents", status: "unavailable" })]));
  });

  it("keeps rendered Services facts as non-authoritative observations when semantic resolution is unavailable", () => {
    const services = buildServicesCopilotContext(servicesInput);
    const serviceRow = services.snapshot.evidence.find(
      (row) => row.data.service === "Payments",
    );
    expect(serviceRow?.data.entity).toMatchObject({
      type: "observation",
      source: "services/catalog",
    });
  });

  const serviceDetailInput = {
    scope: { subscription: ["sub-a"] },
    name: "Payments",
    context: {
      subject: {
        entity_type: "business_service",
        name: "Payments",
        owner: "Payments SRE",
        support_team: "Platform",
        criticality: "high",
        environment: "prod",
      },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["context", "topology"],
    },
    risk: {
      subject: { entity_type: "business_service", name: "Payments" },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["aggregated_risk"],
    },
    impact: {
      subject: { entity_type: "business_service", name: "Payments" },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["dependency_impact"],
    },
    dependencies: [
      {
        id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
        name: "payments-db",
        relation: "depends_on",
        resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
      },
      { id: "app:PaymentsApi", name: "Payments API", relation: "serves" },
    ],
    evidence: [
      {
        source_engine: "graph",
        source_table: "business_service",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds selected service identity, ownership, dependencies, and cited evidence", () => {
    const context = buildServiceDetailCopilotContext(serviceDetailInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "service:Payments",
    });
    expect(context.selectedEntities).toEqual([]);
    // The canonical ARM dependency is retained as a normalized azure entity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.sql/servers/db")).toBe(true);
    // The non-ARM dependency stays a non-authoritative page observation.
    expect(context.snapshot.evidence.some((row) =>
      row.data.relation === "serves"
      && (row.data.entity as { type?: string } | undefined)?.type === "observation")).toBe(true);
    expect(context.snapshot.evidence.some((row) => row.data.owner === "Payments SRE")).toBe(true);
    expect(context.starterQuestions.every((q) => q.specialistId === "resource_health_observability")).toBe(true);
    expect(context.starterQuestions.some((q) => q.label.includes("Payments"))).toBe(true);
  });

  it("keeps service detail facts as observations while retaining ARM dependency identity", () => {
    const context = buildServiceDetailCopilotContext(serviceDetailInput);
    const subject = context.snapshot.evidence.find(
      (row) => row.data.owner === "Payments SRE",
    );
    const domainDependency = context.snapshot.evidence.find(
      (row) => row.data.relation === "serves",
    );
    const armDependency = context.snapshot.evidence.find(
      (row) => row.data.relation === "depends_on",
    );

    expect(subject?.data.entity).toMatchObject({
      type: "observation",
      source: "services/context",
    });
    expect(domainDependency?.data.entity).toMatchObject({
      type: "observation",
      source: "services/impact",
    });
    expect(armDependency?.data.entity).toMatchObject({
      type: "azure",
      resource_id:
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.sql/servers/db",
    });
  });

  it("keeps an unavailable service section distinct from a fresh one", () => {
    const context = buildServiceDetailCopilotContext({
      ...serviceDetailInput,
      risk: { ...serviceDetailInput.risk, available: false, freshness: "unavailable" as const },
    });
    expect(context.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "context", status: "fresh" }),
        expect.objectContaining({ source: "risk", status: "unavailable" }),
      ]),
    );
  });

  it("retains explicit unavailable dependency evidence without inventing dependencies", () => {
    const context = buildServiceDetailCopilotContext({
      ...serviceDetailInput,
      impact: {
        ...serviceDetailInput.impact,
        available: false,
        freshness: "unavailable" as const,
        sourceStatus: { "semantic-graph": "unavailable" },
        warnings: [
          "Dependency evidence is unavailable; no dependency facts are asserted.",
        ],
      },
      dependencies: [],
    });

    expect(context.coverage.dependencies.complete).toBe(false);
    expect(context.snapshot.evidence).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          section: "service_section_status",
          status: "ok",
          data: expect.objectContaining({
            entity: expect.objectContaining({ type: "observation" }),
            detail:
              "Dependency evidence is unavailable; no dependency facts are asserted.",
            section: "impact",
          }),
        }),
      ]),
    );
    expect(context.snapshot.evidence.some((row) =>
      row.data.relation != null)).toBe(false);
  });
});

describe("operational twin Copilot page adapter", () => {
  const twinInput = {
    scope: { subscription: ["sub-a"] },
    twinId: "operational-twin",
    version: "v1",
    previousVersion: "v0",
    observedAt: "2026-01-01T10:00:00Z",
    liveObservedAt: "2026-01-01T10:00:00Z",
    confidence: "medium",
    riskScore: 32,
    sourceStatus: {
      semantic_graph: "current",
      live_operational_sources: "request_time",
      snapshot_materialization: "disabled",
    },
    entities: [
      {
        id: "resource:vm-payroll-1",
        kind: "resource",
        name: "payroll-vm",
        version: "r1",
        state: "current",
        confidence: "high",
        business_service: "Payroll",
        resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/payroll-vm",
      },
      { id: "business_service:Payroll", kind: "business_service", name: "Payroll", version: "b1", state: "current", confidence: "high" },
    ],
    entitiesTotal: 4,
    relationships: [
      { id: "rel-1", source: "resource:vm-payroll-1", target: "business_service:Payroll", type: "supports", confidence: "high", supported: true },
    ],
    relationshipsTotal: 3,
    timeline: [
      { timestamp: "2026-01-01T10:00:00Z", type: "vulnerability_observed", entity: "vulnerability:CVE-2026-0001", summary: "CVE-2026-0001 observed" },
    ],
    timelineTotal: 5,
    traversal: {
      resource_id: "vm-payroll-1",
      path: [
        { id: "resource:vm-payroll-1", kind: "resource", name: "payroll-vm" },
        { id: "business_service:Payroll", kind: "business_service", name: "Payroll" },
      ],
      business_consequence: ["Payroll", "Payroll API"],
    },
    scenario: {
      scenario: "firewall_failure",
      target: "vm-payroll-1",
      likely_impact: "Traffic inspection and hub dependencies degrade.",
      risk_delta: 20,
      impacted_count: 4,
      assumptions: ["Operator validation required"],
    },
    selectedResourceId: "vm-payroll-1",
    available: true,
    freshness: "fresh" as const,
    unsupportedRelationships: ["experimental_edge"],
    staleTemporalEvidence: ["previous revision v0"],
    evidence: [
      {
        source_engine: "twin",
        source_table: "live",
        timestamp: "2026-01-01T10:00:00Z",
        confidence: "medium" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds twin entity, relationship, timeline, traversal, and scenario identities with provenance", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "network",
      page_id: "twin",
    });
    // The selected resource carries a canonical ARM id, so it is retained as a
    // scope-validated azure identity (not a domain guess).
    expect(context.selectedEntities).toEqual([
      {
        type: "azure",
        resource_id: "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/payroll-vm",
      },
    ]);
    // A canonical ARM entity is retained as an azure identity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/payroll-vm")).toBe(true);
    // Relationship identity and provenance are retained.
    expect(context.snapshot.evidence.some((row) =>
      row.data.type === "supports" && row.data.source === "resource:vm-payroll-1")).toBe(true);
    expect(context.snapshot.evidence.find((row) =>
      row.data.type === "supports")?.data.entity).toMatchObject({
        type: "observation",
        source: "twin/relationships",
      });
    // Scenario projection is marked hypothetical, never observed reality.
    expect(context.snapshot.evidence.some((row) =>
      row.data.scenario === "firewall_failure" && row.data.observed === false)).toBe(true);
    // Observed entities are distinguished from scenario projections.
    expect(context.snapshot.evidence.some((row) =>
      row.data.name === "payroll-vm" && row.data.observed === true)).toBe(true);
    expect(context.starterQuestions.every((q) => q.specialistId === "network")).toBe(true);
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    expect(context.snapshot.freshness).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "semantic_graph", status: "fresh" }),
      expect.objectContaining({ source: "live_operational_sources", status: "fresh" }),
      expect.objectContaining({ source: "snapshot_materialization", status: "unavailable" }),
    ]));
    expect(context.snapshot.evidence).toEqual(expect.arrayContaining([
      expect.objectContaining({
        section: "twin/status",
        status: "ok",
        data: expect.objectContaining({
          business_service_count: 1,
          relationship_count: 1,
          risk_detail: expect.stringContaining("heuristic current index of 32"),
          entity: expect.objectContaining({ type: "observation" }),
        }),
      }),
    ]));
  });

  it("states when service impact cannot be asserted from an empty relationship set", () => {
    const context = buildTwinCopilotContext({
      ...twinInput,
      entities: twinInput.entities.filter((entity) => entity.kind !== "business_service"),
      entitiesTotal: 1,
      relationships: [],
      relationshipsTotal: 0,
    });
    const status = context.snapshot.evidence.find(
      (row) => row.section === "twin/status",
    );

    expect(status?.data).toMatchObject({
      business_service_count: 0,
      relationship_count: 0,
      dependency_detail:
        "The current twin contains no relationship evidence, so affected business services and dependencies cannot be asserted.",
    });
    expect(context.snapshot.evidence.some((row) =>
      row.section === "twin/relationships")).toBe(false);
  });

  it("exposes visible/total/truncated coverage for bounded graph and traversal results", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.coverage.entities).toMatchObject({
      visible_count: 2,
      total_count: 4,
      complete: false,
      truncated: true,
    });
    expect(context.coverage.relationships).toMatchObject({
      visible_count: 1,
      total_count: 3,
      truncated: true,
    });
    expect(context.coverage.timeline).toMatchObject({
      visible_count: 1,
      total_count: 5,
      truncated: true,
    });
  });

  it("keeps unsupported relationships and stale temporal evidence uncertain rather than asserted", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "experimental_edge is not a supported twin relationship; treat as uncertain",
        "previous revision v0 is historical evidence and is not asserted as current",
      ]),
    );
  });

  it("distinguishes an unavailable twin from an empty authorized twin", () => {
    const unavailable = buildTwinCopilotContext({
      ...twinInput,
      entities: [],
      entitiesTotal: 0,
      relationships: [],
      relationshipsTotal: 0,
      timeline: [],
      timelineTotal: 0,
      traversal: null,
      scenario: null,
      unsupportedRelationships: [],
      staleTemporalEvidence: [],
      available: false,
      sourceStatus: undefined,
      evidence: [],
    });
    const empty = buildTwinCopilotContext({
      ...twinInput,
      entities: [],
      entitiesTotal: 0,
      relationships: [],
      relationshipsTotal: 0,
      timeline: [],
      timelineTotal: 0,
      traversal: null,
      scenario: null,
      unsupportedRelationships: [],
      staleTemporalEvidence: [],
      available: true,
      sourceStatus: undefined,
      evidence: [],
    });
    expect(unavailable.coverage.entities.complete).toBe(false);
    expect(empty.coverage.entities.complete).toBe(true);
    expect(unavailable.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "twin", status: "unavailable" }),
      ]),
    );
  });
});

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "app");

function discoverRoutePageFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...discoverRoutePageFiles(full));
    } else if (entry.name === "page.tsx") {
      found.push(full);
    }
  }
  return found;
}

function routePathForFile(file: string): string {
  const relative_dir = relative(APP_DIR, dirname(file)).split(sep).join("/");
  return relative_dir === "" ? "/" : `/${relative_dir}`;
}

describe("reviewed-route Copilot disposition gate (COP-02, COP-03)", () => {
  const discoveredRoutes = discoverRoutePageFiles(APP_DIR)
    .map(routePathForFile)
    .sort();
  const registeredRoutes = Object.keys(COPILOT_ROUTE_DISPOSITIONS).sort();

  it("discovers the original 28 reviewed routes plus the inventory asset drilldown", () => {
    expect(discoveredRoutes).toHaveLength(29);
    expect(discoveredRoutes).toContain("/inventory/assets");
  });

  it("makes the registry route inventory equal the filesystem inventory exactly", () => {
    // Bidirectional: no absent disposition (filesystem route missing from the
    // registry) and no extra disposition (registry route with no page file).
    expect(registeredRoutes).toEqual(discoveredRoutes);
  });

  it("gives every discovered route exactly one disposition", () => {
    for (const route of discoveredRoutes) {
      expect(
        COPILOT_ROUTE_DISPOSITIONS[route],
        `route ${route} has no reviewed Copilot disposition`,
      ).toBeDefined();
    }
    expect(new Set(registeredRoutes).size).toBe(registeredRoutes.length);
  });

  it("matches the resolved research disposition table counts", () => {
    const counts = { integrated: 0, dedicated: 0, redirect: 0, excluded: 0 };
    for (const route of registeredRoutes) {
      counts[COPILOT_ROUTE_DISPOSITIONS[route].kind] += 1;
    }
    expect(counts).toEqual({ integrated: 23, dedicated: 3, redirect: 1, excluded: 2 });
  });

  it("names /copilot, /investigate, and /agents as the dedicated surfaces", () => {
    const dedicated = registeredRoutes
      .filter((route) => COPILOT_ROUTE_DISPOSITIONS[route].kind === "dedicated")
      .sort();
    expect(dedicated).toEqual(["/agents", "/copilot", "/investigate"]);
  });

  it("redirects /vulnerabilities to the exact Patch priorities destination", () => {
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/vulnerabilities"];
    expect(disposition).toEqual({
      kind: "redirect",
      target: "/exposure/patch-priorities",
    });
    // The alias route resolves to an integrated adapter only via the canonical
    // Exposure product, so no second adapter is registered for it.
    expect(Object.prototype.hasOwnProperty.call(CORE_COPILOT_PAGE_ADAPTERS, "/vulnerabilities")).toBe(false);
  });

  it("excludes navigation-only search and asset drilldown until reviewed evidence contracts exist", () => {
    const excluded = registeredRoutes.filter(
      (route) => COPILOT_ROUTE_DISPOSITIONS[route].kind === "excluded",
    );
    expect(excluded).toEqual(["/inventory/assets", "/search"]);
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/search"];
    expect(
      disposition.kind === "excluded" && /evidence/i.test(disposition.reason),
    ).toBe(true);
    const assets = COPILOT_ROUTE_DISPOSITIONS["/inventory/assets"];
    expect(assets.kind === "excluded" && /retained evidence snapshot.*selected-asset tool contract/i.test(assets.reason)).toBe(true);
  });

  it("anchors every integrated route on a declared Copilot page kind", () => {
    for (const route of registeredRoutes) {
      const disposition = COPILOT_ROUTE_DISPOSITIONS[route];
      if (disposition.kind === "integrated") {
        expect(typeof disposition.pageKind, `${route} lacks a page kind`).toBe("string");
        expect(disposition.pageKind.length).toBeGreaterThan(0);
      }
    }
  });

  it("keeps copilotPageDisposition backward compatible for integrated routes", () => {
    expect(copilotPageDisposition("/")).toBe("integrated");
    expect(copilotPageDisposition("/inventory")).toBe("integrated");
    expect(copilotPageDisposition("/twin")).toBe("integrated");
  });
});
