import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SubscriptionConnection } from "@/lib/types";
import { ConnectionReadiness } from "./ConnectionReadiness";

const { resources, layers, status, capabilities } = vi.hoisted(() => ({
  resources: vi.fn(), layers: vi.fn(), status: vi.fn(), capabilities: vi.fn(),
}));
vi.mock("@/lib/services", () => ({
  inventoryApi: { resources }, fabricMedallionApi: { layers, capabilities },
  ontologyAutomationApi: { status },
}));

const connection: SubscriptionConnection = {
  connection_id: "conn-a", name: "Production", subscription_id: "sub-a", tenant_id: "tenant",
  scope_key: "a", is_active: true, business_service: "Payroll", environment: "prod", criticality: "high",
  sync_status: "succeeded", sync_record_count: 8175, last_successful_sync_at: "2026-10-16T00:00:00Z",
  health_status: "healthy",
};
const envelope = <T,>(data: T) => ({ data, evidence: [], knowledge_version: "generation-a" });

describe("Connection readiness journey", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resources.mockResolvedValue({ ...envelope({
      resources: [], scope_qualification: { status: "supported", unsupported_dimensions: [] },
    }), pagination: { total: 57 } });
    layers.mockResolvedValue(envelope({ layers: {
      bronze: { healthy: 1, total: 2 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 1 },
    } }));
    status.mockResolvedValue(envelope({ generation: {
      status: "staged", active_generation: "", validation: { passed: false },
      compatibility: { all_consumers_compatible: false },
    } }));
    capabilities.mockResolvedValue(envelope({
      capacity: { status: "healthy" }, semantic_readiness: { status: "deployment-blocked" },
      data_agent_readiness: { status: "disabled" },
    }));
  });

  it("does not infer publication from successful discovery and scopes every independent read", async () => {
    render(<ConnectionReadiness connection={connection} scope={{ environment: ["prod"] }} refreshKey={0} />);
    expect(await screen.findByText(/57 authorized inventory resources/)).toBeInTheDocument();
    expect(screen.getByText(/8175 discovery records/)).toBeInTheDocument();
    const bronze = screen.getByText("Bronze publication").closest("li")!;
    expect(within(bronze).getByText("degraded")).toBeInTheDocument();
    expect(within(screen.getByText("Silver publication").closest("li")!).getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText(/Active pointer: none/)).toBeInTheDocument();
    expect(screen.getByText(/Data Agent disabled/)).toBeInTheDocument();
    const scope = { environment: ["prod"], subscription: ["sub-a"], subscription_connection: ["conn-a"] };
    expect(resources).toHaveBeenCalledWith(scope, 0, 1);
    expect(layers).toHaveBeenCalledWith(scope);
    expect(status).toHaveBeenCalledWith("conn-a", scope);
    expect(capabilities).toHaveBeenCalledWith(scope);
    for (const name of ["bronze publication", "silver publication", "gold publication", "consumer capabilities"]) {
      const href = screen.getByRole("link", { name: `Inspect ${name}` }).getAttribute("href")!;
      const query = new URL(href, "https://example.invalid").searchParams;
      expect(query.getAll("subscription")).toEqual(["sub-a"]);
      expect(query.getAll("subscription_connection")).toEqual(["conn-a"]);
      expect(query.getAll("environment")).toEqual(["prod"]);
    }
    expect(screen.queryByRole("link", { name: "Inspect persisted inventory" })).not.toBeInTheDocument();
    expect(screen.getByText(/destination does not support this selected connection scope/)).toBeInTheDocument();
  });

  it("keeps successful stages visible when one source fails", async () => {
    layers.mockRejectedValueOnce(new Error("Fabric unavailable"));
    render(<ConnectionReadiness connection={connection} scope={{}} refreshKey={0} />);
    expect(await screen.findAllByText("Fabric unavailable")).toHaveLength(3);
    expect(screen.getByText(/57 authorized inventory resources/)).toBeInTheDocument();
    expect(screen.getByText(/8175 discovery records/)).toBeInTheDocument();
  });

  it("ignores delayed inventory evidence after the selected connection changes", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    resources.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const { rerender } = render(<ConnectionReadiness connection={connection} scope={{}} refreshKey={0} />);
    await waitFor(() => expect(resources).toHaveBeenCalledTimes(1));
    resources.mockResolvedValueOnce({ ...envelope({
      resources: [], scope_qualification: { status: "supported", unsupported_dimensions: [] },
    }), pagination: { total: 2 } });
    rerender(<ConnectionReadiness connection={{ ...connection, connection_id: "conn-b", subscription_id: "sub-b" }} scope={{}} refreshKey={0} />);
    expect(await screen.findByText(/2 authorized inventory resources/)).toBeInTheDocument();
    resolve({ ...envelope({ resources: [] }), knowledge_version: "old-scope" });
    await waitFor(() => expect(screen.queryByText(/old-scope/)).not.toBeInTheDocument());
  });

  it.each([undefined, {
    status: "unsupported", unsupported_dimensions: ["subscription_connection"],
    reason: "connection_attribution_unavailable",
  }])("does not present an unqualified connection response as zero resources", async scopeQualification => {
    resources.mockResolvedValueOnce({
      ...envelope({
        resources: [], scope_qualification: scopeQualification,
        generation_id: "published-generation",
        family_availability: { paas: { family: "paas", state: "ready" } },
      }),
      pagination: { total: 0 },
    });
    render(<ConnectionReadiness connection={connection} scope={{}} refreshKey={0} />);
    expect(await screen.findByText(/Connection-scoped inventory count is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/0 authorized inventory resources/)).not.toBeInTheDocument();
    expect(screen.getByText(/published-generation/)).toBeInTheDocument();
    const inventory = screen.getByText("Persisted inventory").closest("li")!;
    expect(within(inventory).getByText("unknown")).toBeInTheDocument();
    expect(resources).toHaveBeenCalledWith({
      subscription: ["sub-a"], subscription_connection: ["conn-a"],
    }, 0, 1);
  });

  it("retains a qualified genuine zero and the reported publication generation", async () => {
    resources.mockResolvedValueOnce({
      ...envelope({
        resources: [], generation_id: "empty-generation",
        scope_qualification: { status: "supported", unsupported_dimensions: [] },
      }),
      pagination: { total: 0 },
    });
    render(<ConnectionReadiness connection={connection} scope={{}} refreshKey={0} />);
    expect(await screen.findByText(/0 authorized inventory resources/)).toBeInTheDocument();
    expect(screen.getByText(/empty-generation/)).toBeInTheDocument();
    expect(screen.queryByText(/generation is not reported/)).not.toBeInTheDocument();
  });
});
