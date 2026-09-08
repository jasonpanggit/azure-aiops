import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";
import type { ScopeSelection } from "@/lib/scope";
import type {
  Envelope,
  OntologyAutomationStatus,
  OntologyEvaluation,
  OntologyEvaluationSnapshot,
  OntologyGeneration,
  OntologyProposal,
  OntologyProposalReviewRequest,
  OntologyRollbackRequest,
  OntologyRun,
  OntologyRunMutationRequest,
  OntologyRunNowRequest,
} from "@/lib/types";

const {
  create,
  fabricCapabilities,
  fabricDataset,
  fabricGovernance,
  fabricIngestionHistory,
  fabricLayers,
  fabricManifest,
  getConnection,
  health,
  list,
  mapMetadata,
  ontologyCancelRun,
  ontologyEvaluation,
  ontologyEvaluations,
  ontologyGeneration,
  ontologyProposals,
  ontologyPublications,
  ontologyRetryRun,
  ontologyReviewProposal,
  ontologyRollbackGeneration,
  ontologyRunNow,
  ontologyRuns,
  ontologyStatus,
  sync,
  updateConnection,
} = vi.hoisted(() => ({
  create: vi.fn(),
  fabricCapabilities: vi.fn(),
  fabricDataset: vi.fn(),
  fabricGovernance: vi.fn(),
  fabricIngestionHistory: vi.fn(),
  fabricLayers: vi.fn(),
  fabricManifest: vi.fn(),
  getConnection: vi.fn(),
  health: vi.fn(),
  list: vi.fn(),
  mapMetadata: vi.fn(),
  ontologyCancelRun: vi.fn(),
  ontologyEvaluation: vi.fn(),
  ontologyEvaluations: vi.fn(),
  ontologyGeneration: vi.fn(),
  ontologyProposals: vi.fn(),
  ontologyPublications: vi.fn(),
  ontologyRetryRun: vi.fn(),
  ontologyReviewProposal: vi.fn(),
  ontologyRollbackGeneration: vi.fn(),
  ontologyRunNow: vi.fn(),
  ontologyRuns: vi.fn(),
  ontologyStatus: vi.fn(),
  sync: vi.fn(),
  updateConnection: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: unknown) => input,
  connectionsApi: {
    create,
    get: getConnection,
    health,
    list,
    mapMetadata,
    sync,
    update: updateConnection,
    validate: vi.fn(),
  },
  fabricMedallionApi: {
    layers: fabricLayers,
    dataset: fabricDataset,
    manifest: fabricManifest,
    governance: fabricGovernance,
    ingestionHistory: fabricIngestionHistory,
    capabilities: fabricCapabilities,
  },
  ontologyAutomationApi: {
    status: ontologyStatus,
    runs: ontologyRuns,
    run: vi.fn(),
    runNow: ontologyRunNow,
    cancelRun: ontologyCancelRun,
    retryRun: ontologyRetryRun,
    proposals: ontologyProposals,
    proposal: vi.fn(),
    reviewProposal: ontologyReviewProposal,
    generation: ontologyGeneration,
    publications: ontologyPublications,
    rollbackGeneration: ontologyRollbackGeneration,
    evaluation: ontologyEvaluation,
    evaluations: ontologyEvaluations,
  },
}));

import ConnectionsPage from "./page";

function renderConnectionsPage() {
  return render(
    <ScopeProvider>
      <ConnectionsPage />
    </ScopeProvider>
  );
}

function renderConnectionsPageWithScope(subscriptionId: string) {
  return render(
    <ScopeProvider initialScope={{ subscription: [subscriptionId] }}>
      <ConnectionsPage />
    </ScopeProvider>
  );
}

const emptyEnvelope = {
  data: [],
  evidence: [],
  scope: {},
  pagination: { offset: 0, limit: 100, total: 0, next_offset: null },
};

const connection = {
  connection_id: "prod",
  name: "Production",
  subscription_id: "00000000-0000-0000-0000-000000000001",
  tenant_id: "00000000-0000-0000-0000-000000000002",
  scope_key: "prod",
  is_active: true,
  health_status: "healthy",
  sync_status: "succeeded",
  last_successful_sync_at: "2026-01-01T00:00:00Z",
  business_service: "Payments",
  environment: "prod",
  criticality: "critical",
};


type TestEnvelope<T> = {
  data: T;
  evidence: Array<{ source_engine: string; source_table: string; timestamp: string; confidence: string }>;
  scope: Record<string, string[]>;
  knowledge_version: string;
  warnings: string[];
};

function envelope<T>(data: T): TestEnvelope<T> {
  return {
    data,
    evidence: [{ source_engine: "fabric.medallion_health", source_table: "metadata_source_status", timestamp: "2026-01-01T00:00:00Z", confidence: "high" }],
    scope: {},
    knowledge_version: "fabric-test",
    warnings: [],
  };
}

function dataset(tableName: string, availability: string, rowCount: number) {
  return {
    table_name: tableName,
    availability,
    freshness: availability === "unavailable" ? "unknown" : "fresh",
    quality: availability === "unavailable" ? "unknown" : "complete",
    row_count: rowCount,
    stale_after_seconds: 3600,
    observed_at: "2026-01-01T00:00:00Z",
    ingested_at: "2026-01-01T00:00:00Z",
    watermark: "2026-01-01T00:00:00Z",
    error: availability === "unavailable" ? "capacity paused" : "",
    lineage_ref: `lineage://${tableName}`,
  };
}

function capabilitiesFor(tableNames: string[]) {
  return envelope({
    capacity: { status: "healthy", capacity_name: "cap-aiops" },
    data_access_roles: { status: "available", total_roles: 2, roles: [] },
    maintenance: { status: "healthy", last_run_at: "2026-01-01T00:00:00Z", activity_name: "vacuum" },
    semantic_readiness: { status: "deployment-blocked", reason: "preview deployment requires manual promotion" },
    data_agent_readiness: { status: "available", configured: true },
    lineage: {
      native_lineage_url: "https://fabric.microsoft.com/workspace/workspace-abc",
      datasets: tableNames.map((table_name) => ({ table_name, status: "healthy", lineage_ref: `lineage://${table_name}`, lineage: {} })),
    },
  });

  it("invalidates the selected connection and pending section reads when effective scope changes", async () => {
    const secondConnection = {
      ...connection,
      connection_id: "nonprod",
      name: "Non-production",
      subscription_id: "00000000-0000-0000-0000-000000000099",
    };
    list.mockImplementation((scope: ScopeSelection) =>
      Promise.resolve({
        ...emptyEnvelope,
        data: scope.subscription?.includes(secondConnection.subscription_id)
          ? [secondConnection]
          : [connection],
      }),
    );

    function ScopeSwitch() {
      const { setScope } = useScope();
      return (
        <>
          <button type="button" onClick={() => setScope({ subscription: [secondConnection.subscription_id] })}>
            Narrow scope
          </button>
          <ConnectionsPage />
        </>
      );
    }

    render(
      <ScopeProvider initialScope={{ subscription: [connection.subscription_id] }}>
        <ScopeSwitch />
      </ScopeProvider>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));
    expect(await screen.findByRole("combobox", { name: "Connection" })).toHaveValue(connection.connection_id);

    fireEvent.click(screen.getByRole("button", { name: "Narrow scope" }));

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Connection" })).toHaveValue(secondConnection.connection_id);
      expect(ontologyEvaluation).toHaveBeenLastCalledWith(
        secondConnection.connection_id,
        { subscription: [secondConnection.subscription_id] },
      );
    });
  });
}

function mockFabricHealth(tableNames: string[] = ["bronze_resources", "silver_incidents", "gold_operational_context"]) {
  fabricLayers.mockResolvedValue(envelope({
    layers: {
      bronze: { healthy: 1, total: 1 },
      silver: { healthy: 1, total: 1 },
      gold: { healthy: 1, total: 1 },
    },
  }));
  fabricCapabilities.mockResolvedValue(capabilitiesFor(tableNames));
  fabricManifest.mockResolvedValue(envelope({ entries: [] }));
  fabricGovernance.mockResolvedValue(envelope({ ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0, gaps: [] }));
  fabricIngestionHistory.mockResolvedValue(envelope({ runs: [] }));
  fabricDataset.mockImplementation((tableName: string) => Promise.resolve(envelope(dataset(tableName, "healthy", 12))));
}

const ontologyRun = {
  run_id: "ODR-001",
  connection_id: connection.connection_id,
  source_generation_id: "generation-1",
  trigger: "manual",
  status: "running",
  revision: 4,
  attempt_count: 1,
  max_attempts: 3,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:05:00Z",
  deadline_at: "2026-01-01T01:00:00Z",
  next_attempt_at: null,
  lease_expires_at: "2026-01-01T00:10:00Z",
  fencing_token: 8,
  cancel_requested: false,
  checkpoint: {
    name: "discovering",
    payload: { proposal_count: 3, accepted_count: 1, published_count: 0 },
  },
  failure_class: null,
  message: "",
  can_cancel: true,
  can_retry: false,
  disabled_reasons: { cancel: "", retry: "run_not_terminal" },
} as const;

const ontologyGenerationData = {
  status: "active",
  active_generation: "generation-2",
  prior_generation: "generation-1",
  source_generation: "generation-1",
  pointer_etag: "etag-2",
  fence: 8,
  complete: true,
  validation: { passed: true, errors: [], model_derived_relationships: 0 },
  compatibility: { all_consumers_compatible: true },
  publication: { intent: "validated", result: "published" },
  can_rollback: true,
  rollback_disabled_reason: "",
} as const;

const ontologySnapshot = {
  contract_version: "1.0.0",
  snapshot_id: `EVS-${"A".repeat(64)}`,
  scope_key: `scope-${"a".repeat(32)}`,
  scope_hash: "a".repeat(32),
  observed_at: "2026-01-01T00:00:00Z",
  evaluated_at: "2026-01-01T00:05:00Z",
  expires_at: "2026-01-01T01:05:00Z",
  lineage: {
    dataset_version: "wave0-v1",
    dataset_hash: "1".repeat(64),
    prompt_version: "curator-v3",
    prompt_hash: "2".repeat(64),
    schema_version: "proposal-v2",
    schema_hash: "3".repeat(64),
    model_version: "gpt-5.4-mini",
    model_hash: "4".repeat(64),
    agent_version: "ontology-curator-v5",
    agent_hash: "5".repeat(64),
    policy_version: "ontology-policy-v7",
    policy_hash: "6".repeat(64),
  },
  source_expiries: [
    {
      source: "azure-resource-graph",
      observed_at: "2026-01-01T00:00:00Z",
      expires_at: "2026-01-01T01:05:00Z",
    },
  ],
  slice_metrics: [
    {
      metric: "precision",
      slice_key: "overall",
      numerator: 99,
      denominator: 100,
      value: 0.99,
      critical: true,
    },
  ],
  thresholds: [
    { metric: "precision", slice_key: "overall", minimum: 0.98, critical: true },
  ],
  critical_failures: [],
  release_eligible: true,
  artifact_references: [],
} as const;

function ontologyStatusData(currentRun: typeof ontologyRun | null = ontologyRun) {
  return {
    scheduler: {
      owner: "external_job",
      api_owned: false,
      state: "available",
      can_run_now: currentRun === null,
      run_now_disabled_reason: currentRun === null ? "" : "active_run_exists",
      enabled: true,
      cadence: "Every 6 hours",
      next_due_at: "2026-01-01T06:00:00Z",
      last_trigger_at: "2026-01-01T00:00:00Z",
    },
    current_run: currentRun,
    incremental: {
      checkpoint: currentRun?.checkpoint.name ?? "",
      pending_relationships: [],
      pending_count: 0,
      added_count: 4,
      changed_count: 2,
      retired_count: 1,
      unresolved_count: 0,
      stale_count: 0,
      last_reconciliation_at: "2026-01-01T00:05:00Z",
      last_reconciliation_result: "succeeded",
    },
    proposals: { pending_count: 0, total: 0 },
    generation: ontologyGenerationData,
    evaluation: {
      status: "fresh",
      reason: "evaluation_snapshot_fresh",
      pointer_revision: 2,
      snapshot: ontologySnapshot,
      release_eligible: true,
      release_disabled_reason: "",
    },
  };
}

function mockOntologyAutomation() {
  ontologyStatus.mockResolvedValue(envelope(ontologyStatusData()));
  ontologyRuns.mockResolvedValue(envelope([ontologyRun]));
  ontologyProposals.mockResolvedValue(envelope([]));
  ontologyGeneration.mockResolvedValue(envelope(ontologyGenerationData));
  ontologyPublications.mockResolvedValue(envelope([ontologyRun]));
  ontologyEvaluation.mockResolvedValue(envelope(ontologyStatusData().evaluation));
  ontologyEvaluations.mockResolvedValue(envelope([ontologySnapshot]));
  ontologyRunNow.mockResolvedValue(envelope({ ...ontologyRun, status: "queued" }));
  ontologyCancelRun.mockResolvedValue(envelope({ ...ontologyRun, status: "cancelled" }));
  ontologyRetryRun.mockResolvedValue(envelope({ ...ontologyRun, status: "retrying" }));
  ontologyReviewProposal.mockResolvedValue(
    envelope({ proposal_id: "OPR-1", status: "accepted", revision: 2, events: [] }),
  );
  ontologyRollbackGeneration.mockResolvedValue(envelope(ontologyGenerationData));
}

describe("Ontology automation typed client contract", () => {
  it("requires a selected connection and effective scope for every durable read", () => {
    type OntologyApi = typeof import("@/lib/services").ontologyAutomationApi;

    expectTypeOf<Parameters<OntologyApi["status"]>>().toEqualTypeOf<
      [connectionId: string, scope: ScopeSelection]
    >();
    expectTypeOf<Parameters<OntologyApi["run"]>>().toEqualTypeOf<
      [connectionId: string, runId: string, scope: ScopeSelection]
    >();
    expectTypeOf<Parameters<OntologyApi["proposal"]>>().toEqualTypeOf<
      [connectionId: string, proposalId: string, scope: ScopeSelection]
    >();
    expectTypeOf<Parameters<OntologyApi["generation"]>>().toEqualTypeOf<
      [connectionId: string, scope: ScopeSelection]
    >();
    expectTypeOf<Parameters<OntologyApi["evaluation"]>>().toEqualTypeOf<
      [connectionId: string, scope: ScopeSelection]
    >();

    expectTypeOf<ReturnType<OntologyApi["status"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyAutomationStatus>>
    >();
    expectTypeOf<ReturnType<OntologyApi["generation"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyGeneration>>
    >();
    expectTypeOf<ReturnType<OntologyApi["evaluation"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyEvaluation>>
    >();
    expectTypeOf<ReturnType<OntologyApi["evaluations"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyEvaluationSnapshot[]>>
    >();
  });

  it("requires server concurrency values on every ontology mutation", () => {
    type OntologyApi = typeof import("@/lib/services").ontologyAutomationApi;

    expectTypeOf<Parameters<OntologyApi["runNow"]>>().toEqualTypeOf<
      [connectionId: string, scope: ScopeSelection, payload: OntologyRunNowRequest]
    >();
    expectTypeOf<Parameters<OntologyApi["cancelRun"]>>().toEqualTypeOf<
      [connectionId: string, runId: string, scope: ScopeSelection, payload: OntologyRunMutationRequest]
    >();
    expectTypeOf<Parameters<OntologyApi["retryRun"]>>().toEqualTypeOf<
      [connectionId: string, runId: string, scope: ScopeSelection, payload: OntologyRunMutationRequest]
    >();
    expectTypeOf<Parameters<OntologyApi["reviewProposal"]>>().toEqualTypeOf<
      [connectionId: string, proposalId: string, scope: ScopeSelection, payload: OntologyProposalReviewRequest]
    >();
    expectTypeOf<Parameters<OntologyApi["rollbackGeneration"]>>().toEqualTypeOf<
      [connectionId: string, generationId: string, scope: ScopeSelection, payload: OntologyRollbackRequest]
    >();

    expectTypeOf<ReturnType<OntologyApi["runNow"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyRun>>
    >();
    expectTypeOf<ReturnType<OntologyApi["reviewProposal"]>>().toEqualTypeOf<
      Promise<Envelope<OntologyProposal["review"]>>
    >();
  });
});

describe("Connections page Ontology automation tab", () => {
  beforeEach(() => {
    list.mockReset();
    ontologyStatus.mockReset();
    ontologyRuns.mockReset();
    ontologyProposals.mockReset();
    ontologyGeneration.mockReset();
    ontologyPublications.mockReset();
    ontologyEvaluation.mockReset();
    ontologyEvaluations.mockReset();
    ontologyRunNow.mockReset();
    ontologyCancelRun.mockReset();
    ontologyRetryRun.mockReset();
    ontologyReviewProposal.mockReset();
    ontologyRollbackGeneration.mockReset();
    list.mockResolvedValue({ ...emptyEnvelope, data: [connection] });
    mockOntologyAutomation();
  });

  it("adds the approved tab and binds every durable section to the selected in-scope connection", async () => {
    renderConnectionsPageWithScope(connection.subscription_id);

    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));

    expect(await screen.findByRole("heading", { name: "Ontology automation" })).toBeInTheDocument();
    expect(screen.getByText("Monitor scheduled discovery, review proposed relationships, and manage validated Fabric ontology generations for one onboarded connection.")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "Ontology automation" })).toHaveAttribute("id", "ontology-automation-panel");
    expect(screen.getByRole("combobox", { name: "Connection" })).toHaveValue(connection.connection_id);

    await waitFor(() => {
      const expectedScope = { subscription: [connection.subscription_id] };
      expect(ontologyStatus).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyRuns).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyProposals).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyGeneration).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyPublications).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyEvaluation).toHaveBeenCalledWith(connection.connection_id, expectedScope);
      expect(ontologyEvaluations).toHaveBeenCalledWith(connection.connection_id, expectedScope);
    });
  });

  it("uses only server eligibility and preserves stale evaluation evidence with the disabled reason", async () => {
    ontologyStatus.mockResolvedValue(envelope({
      ...ontologyStatusData(),
      scheduler: {
        ...ontologyStatusData().scheduler,
        can_run_now: false,
        run_now_disabled_reason: "active_run_exists",
      },
      current_run: {
        ...ontologyRun,
        can_cancel: false,
        disabled_reasons: { cancel: "lease_lost", retry: "run_not_terminal" },
      },
    }));
    ontologyGeneration.mockResolvedValue(envelope({
      ...ontologyGenerationData,
      can_rollback: false,
      rollback_disabled_reason: "publisher_action_unavailable",
    }));
    ontologyEvaluation.mockResolvedValue(envelope({
      status: "stale",
      reason: "evaluation_snapshot_expired",
      pointer_revision: 2,
      snapshot: ontologySnapshot,
      release_eligible: false,
      release_disabled_reason: "evaluation_snapshot_expired",
    }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));

    expect(await screen.findByText(ontologySnapshot.snapshot_id)).toBeInTheDocument();
    expect(screen.getByText("Evaluation snapshot is stale. Release remains disabled until fresh evaluation evidence is restored.")).toBeInTheDocument();
    expect(screen.getByText(/evaluation_snapshot_expired/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run discovery now" })).toBeDisabled();
    expect(screen.getByText("active_run_exists")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    expect(screen.getByText("lease_lost")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back generation" })).toBeDisabled();
    expect(screen.getByText("publisher_action_unavailable")).toBeInTheDocument();
  });

  it("keeps successful sections visible when sibling ontology sources fail", async () => {
    ontologyProposals.mockRejectedValue(new Error("proposal provider offline"));
    ontologyGeneration.mockRejectedValue(new Error("generation pointer offline"));
    ontologyRuns.mockRejectedValue(new Error("run history offline"));
    ontologyPublications.mockRejectedValue(new Error("publication history offline"));
    ontologyEvaluation.mockRejectedValue(new Error("evaluation store offline"));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));

    expect(await screen.findByText("Relationship proposals are unavailable. No review decision was changed. Refresh proposals before acting.")).toBeInTheDocument();
    expect(screen.getByText("Ontology generation status is unavailable. Do not assume publication completed. Refresh generation status.")).toBeInTheDocument();
    expect(screen.getByText("Discovery run history is unavailable. Current run state was not changed. Refresh run history.")).toBeInTheDocument();
    expect(screen.getByText("Publication attempt history is unavailable. The active generation was not changed. Refresh publication history.")).toBeInTheDocument();
    expect(screen.getByText("Agent evaluation status is unavailable. Auto-accept remains disabled until evaluation evidence is restored.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Scheduler state" })).toBeInTheDocument();
    expect(screen.getByText("Incremental discovery")).toBeInTheDocument();
  });

  it("renders exact empty and degraded copy without conflating agent and deterministic discovery", async () => {
    ontologyStatus.mockResolvedValue(envelope({
      ...ontologyStatusData(null),
      evaluation: {
        status: "missing",
        reason: "evaluation_pointer_missing",
        pointer_revision: null,
        snapshot: null,
        release_eligible: false,
        release_disabled_reason: "evaluation_pointer_missing",
      },
    }));
    ontologyRuns.mockResolvedValue(envelope([]));
    ontologyProposals.mockResolvedValue(envelope([]));
    ontologyPublications.mockResolvedValue(envelope([]));
    ontologyEvaluation.mockResolvedValue(envelope({
      status: "missing",
      reason: "evaluation_pointer_missing",
      pointer_revision: null,
      snapshot: null,
      release_eligible: false,
      release_disabled_reason: "evaluation_pointer_missing",
    }));
    ontologyEvaluations.mockResolvedValue(envelope([]));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));

    expect(await screen.findByText("Ontology discovery has not run for this connection")).toBeInTheDocument();
    expect(screen.getByText("No relationship proposals need review")).toBeInTheDocument();
    expect(screen.getByText("No discovery run history is available for this connection.")).toBeInTheDocument();
    expect(screen.getByText("No ontology publication attempts are available. Existing Fabric data is unchanged.")).toBeInTheDocument();
    expect(screen.getByText("No relationships are waiting for unresolved endpoints.")).toBeInTheDocument();
    expect(screen.getByText("Relationship proposal agent is unavailable. Deterministic discovery can continue; no model proposals will be promoted.")).toBeInTheDocument();
  });

  it("uses exact destructive confirmations and observed concurrency values", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Ontology automation" }));

    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(confirm).toHaveBeenCalledWith(
      "Cancel run ODR-001? Work stops at the next safe checkpoint. The active ontology generation will not change.",
    );
    await waitFor(() => {
      expect(ontologyCancelRun).toHaveBeenCalledWith(
        connection.connection_id,
        ontologyRun.run_id,
        {},
        expect.objectContaining({ expected_revision: 4 }),
      );
    });
    expect(await screen.findByText("Cancellation requested for run ODR-001.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Roll back generation" }));
    expect(confirm).toHaveBeenCalledWith(
      "Roll back to generation generation-1? This changes the active pointer and preserves both generations and the audit history.",
    );
    await waitFor(() => {
      expect(ontologyRollbackGeneration).toHaveBeenCalledWith(
        connection.connection_id,
        ontologyGenerationData.prior_generation,
        {},
        expect.objectContaining({
          expected_etag: ontologyGenerationData.pointer_etag,
          idempotency_key: expect.any(String),
        }),
      );
    });
    expect(await screen.findByText("Rollback requested for generation generation-1.")).toBeInTheDocument();
    confirm.mockRestore();
  });
});

describe("Connections page Fabric Medallion tab", () => {
  beforeEach(() => {
    create.mockReset();
    getConnection.mockReset();
    health.mockReset();
    list.mockReset();
    mapMetadata.mockReset();
    sync.mockReset();
    updateConnection.mockReset();
    fabricLayers.mockReset();
    fabricCapabilities.mockReset();
    fabricManifest.mockReset();
    fabricGovernance.mockReset();
    fabricIngestionHistory.mockReset();
    fabricDataset.mockReset();
    list.mockResolvedValue({ ...emptyEnvelope, data: [connection] });
    mockFabricHealth();
  });

  it("switches between Subscriptions and Fabric Medallion panels without rewriting subscription content", async () => {
    renderConnectionsPage();

    expect(await screen.findByText("Production")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(fabricPanel).toHaveAttribute("id", "fabric-medallion-panel");
    expect(within(fabricPanel).getByText("Bronze tables")).toBeInTheDocument();
    expect(within(fabricPanel).getByRole("heading", { name: /Bronze layer/i })).toBeInTheDocument();
    const subscriptionSelect = screen.getByDisplayValue(/Production/);
    expect(subscriptionSelect).toBeInTheDocument();
    expect(document.querySelector("#subscriptions-panel")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));

    expect(screen.getByText("Production")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "Subscriptions" })).not.toHaveAttribute("hidden");
  });

  it("clears manual sync progress when inventory is terminal but ontology remains queued", async () => {
    const failedConnection = {
      ...connection,
      health_status: "failed",
      sync_status: "failed",
    };
    list.mockResolvedValue({ ...emptyEnvelope, data: [failedConnection] });
    sync.mockResolvedValue({
      data: {
        sync_state: {
          status: "running",
          stage: "queued",
          stage_message: "manual sync queued",
          progress_pct: 0,
          record_count: 12605,
        },
      },
    });
    health.mockResolvedValue({
      data: {
        connections: [
          {
            connection_id: failedConnection.connection_id,
            sync: {
              status: "failed",
              stage: "failed",
              stage_message: "inventory failed",
              message: "inventory failed",
              progress_pct: 100,
              record_count: 12605,
            },
            durable_run: {
              run_id: "ODR-QUEUED",
              status: "queued",
              checkpoint: "queued",
            },
          },
        ],
      },
    });

    renderConnectionsPage();

    fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled();
      expect(screen.getByText("inventory failed")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Sync in progress:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Syncing…" })).not.toBeInTheDocument();
  });

  it("passes subscription scope to every Fabric Medallion API call", async () => {
    renderConnectionsPageWithScope(connection.subscription_id);
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(within(fabricPanel).getByText("Bronze tables")).toBeInTheDocument();
    await waitFor(() => {
      expect(fabricLayers).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricManifest).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricGovernance).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricIngestionHistory).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricCapabilities).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricDataset).toHaveBeenCalledWith("bronze_resources", { subscription: [connection.subscription_id] });
    });
  });

  it("isolates Bronze and Silver dataset failures while Gold data and summary metrics stay populated", async () => {
    mockFabricHealth(["bronze_resources", "silver_incidents", "gold_operational_context"]);
    fabricLayers.mockResolvedValue(envelope({
      layers: {
        bronze: { healthy: 0, total: 1 },
        silver: { healthy: 0, total: 1 },
        gold: { healthy: 1, total: 1 },
      },
    }));
    fabricDataset.mockImplementation((tableName: string) => {
      if (tableName.startsWith("gold_")) return Promise.resolve(envelope(dataset(tableName, "healthy", 140)));
      return Promise.reject(new Error(`${tableName} unavailable`));
    });

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    expect(await screen.findByText("Bronze layer health is unavailable")).toBeInTheDocument();
    expect(screen.getByText("Silver layer health is unavailable")).toBeInTheDocument();
    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(within(fabricPanel).getAllByText("gold_operational_context").length).toBeGreaterThan(0);
    expect(screen.getByText("Gold tables")).toBeInTheDocument();
    expect(within(fabricPanel).getAllByText("1/1").length).toBeGreaterThan(0);
  });

  it("distinguishes healthy-empty zero rows from unavailable datasets", async () => {
    mockFabricHealth(["bronze_empty", "gold_unavailable"]);
    fabricDataset.mockImplementation((tableName: string) => {
      if (tableName === "bronze_empty") return Promise.resolve(envelope(dataset(tableName, "healthy-empty", 0)));
      return Promise.resolve(envelope(dataset(tableName, "unavailable", 0)));
    });

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    const healthyEmptyBadge = (await within(fabricPanel).findAllByText("Healthy · Empty"))[0];
    expect(healthyEmptyBadge).toHaveClass("status-success");
    expect((await within(fabricPanel).findAllByText(/0 rows \(expected\)/)).length).toBeGreaterThan(0);
    const unavailableBadge = within(fabricPanel).getAllByText("Unavailable")[0];
    expect(unavailableBadge).toHaveClass("status-critical");
    expect(unavailableBadge).not.toHaveTextContent("Healthy · Empty");
  });

  it("shows retry guidance only for failed ingestion rows and never renders inert retry buttons", async () => {
    fabricIngestionHistory.mockResolvedValue(envelope({
      runs: [
        { projection_name: "gold_operational_context", status: "failed", attempted_at: "2026-01-01T00:00:00Z", attempts: 3, retry_eligible: true, message: "warehouse timeout", source: "source-status" },
        { projection_name: "silver_incidents", status: "unavailable", attempted_at: "2026-01-01T00:00:00Z", attempts: 1, retry_eligible: false, message: "capacity paused", source: "source-status" },
      ],
    }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    expect(await screen.findByText("Ingestion failed — 3 of 3 attempts exhausted · last error: warehouse timeout")).toBeInTheDocument();
    expect(screen.getByText("Source unavailable — Fabric capacity or workspace could not be reached")).toBeInTheDocument();
    expect(screen.getByText("Retry via subscription sync")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry ingestion/i })).not.toBeInTheDocument();
  });

  it("links each subscription row to its own Fabric Medallion page", async () => {
    renderConnectionsPage();

    expect(await screen.findByText("Production")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Fabric Medallion" }));
    const subscriptionSelect = await screen.findByDisplayValue(
      new RegExp(`${connection.name}.*${connection.subscription_id}`)
    );
    expect(subscriptionSelect).toBeInTheDocument();
    expect(subscriptionSelect).toHaveAttribute("name", "subscriptionId");
  });

  it("explains an unpublished watermark instead of labelling it unknown", async () => {
    mockFabricHealth(["bronze_resources"]);
    fabricDataset.mockResolvedValue(envelope({ ...dataset("bronze_resources", "healthy", 4), watermark: "" }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(await within(fabricPanel).findByText("Not yet published")).toBeInTheDocument();
    expect(within(fabricPanel).queryByText("watermark unknown")).not.toBeInTheDocument();
    expect(within(fabricPanel).getAllByText(/Watermark/).length).toBeGreaterThan(0);
  });

  it("renders a populated watermark as a caught-up checkpoint", async () => {
    mockFabricHealth(["bronze_resources"]);
    fabricDataset.mockResolvedValue(envelope(dataset("bronze_resources", "healthy", 4)));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(await within(fabricPanel).findByText(/Caught up to/)).toBeInTheDocument();
  });

  it("groups lifecycle contracts by disposition with blockers listed first", async () => {
    fabricManifest.mockResolvedValue(envelope({
      entries: [
        { projection_name: "gold_active_one", disposition: "active", compatibility_version: "1.0.0", updated_at: "2026-01-01T00:00:00Z" },
        { projection_name: "gold_blocked_one", disposition: "deployment-blocked", compatibility_version: "1.0.0", updated_at: "2026-01-01T00:00:00Z", retired_reason: "semantic model not deployed" },
      ],
    }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric Medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric Medallion" });
    expect(await within(fabricPanel).findByText("gold_blocked_one")).toBeInTheDocument();
    expect(within(fabricPanel).getByText("gold_active_one")).toBeInTheDocument();
    expect(within(fabricPanel).getByText(/semantic model not deployed/)).toBeInTheDocument();

    const names = within(fabricPanel)
      .getAllByText(/^gold_(blocked|active)_one$/)
      .map((node) => node.textContent);
    expect(names.indexOf("gold_blocked_one")).toBeLessThan(names.indexOf("gold_active_one"));
  });
});
