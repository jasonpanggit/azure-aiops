import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import type { AgentRuntimeReadiness as Report, AutonomousAgent } from "@/lib/types";
import { AgentRuntimeReadiness } from "./AgentRuntimeReadiness";

const { runtimeReadiness } = vi.hoisted(() => ({ runtimeReadiness: vi.fn() }));
vi.mock("@/lib/services", () => ({ multiAgentApi: { runtimeReadiness } }));
const envelope = (data: Report) => ({ data, scope: {}, evidence: [], warnings: [] });
const report: Report = {
  source: "api.ProviderRuntime", report_kind: "cached_process_state", reported_at: "2026-10-17T10:00:00Z",
  providers: {
    network: { state: "stale", configured: true, loaded: true, cache_key_stale: true,
      freshness: "2020-01-01T00:00:00Z", ontology_version: "old-generation",
      loaded_at: "2026-10-01T00:00:00Z", last_success_at: "2026-10-01T00:00:00Z",
      last_attempt_at: "2026-10-02T00:00:00Z", degraded_reason: "Snapshot is old" },
    network_agent: null,
  },
};
const agents: AutonomousAgent[] = [{
  id: "network", name: "Network agent", role: "Network", tools: [], depends_on: [], keywords: [],
  foundry: { status: "available_inactive", configured: false, version: "manifest-default",
    activation_source: "unconfigured", version_pinning_required: true,
    candidate: { name: "candidate-network", provider_version_id: "provider-version-1", candidate_version: "candidate-1",
      source: "validated_candidate_artifact", source_revision: "candidate-revision", release: "release-1", validated_at: "2026-10-01T00:00:00Z" } },
}];
const props = { scope: {}, agents, catalogLoading: false, catalogError: "" };
function open() {
  const details = screen.getByText("Runtime readiness and version evidence").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  const declarations = details.querySelector<HTMLDetailsElement>(".agents-readiness-declarations");
  if (declarations) declarations.open = true;
  return details;
}

describe("independently sourced agent runtime readiness", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runtimeReadiness.mockResolvedValue(envelope(report));
  });

  it("loads only when opened, preserving all nine dimensions without a provider refresh", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-value`]]));
    render(<AgentRuntimeReadiness {...props} scope={scope} />);
    expect(runtimeReadiness).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText(/Snapshot is old/)).toBeVisible();
    expect(runtimeReadiness).toHaveBeenCalledWith(scope, { signal: expect.any(AbortSignal) });
    expect(screen.getByText(/no live Foundry, APIM or MCP probe/)).toBeVisible();
    const row = screen.getByText("network", { exact: true }).closest("li")!;
    expect(within(row).getByText("stale")).toBeVisible();
    expect(within(row).getByText(/Cache key changed: Yes/)).toBeVisible();
    expect(within(row).getByText(/old-generation/)).toBeVisible();
    expect(screen.getByText(/No cached observation was reported/)).toBeVisible();
    expect(screen.getByText(/Active version: Not active/)).toBeVisible();
    expect(screen.getByText(/provider version provider-version-1/)).toBeVisible();
    expect(screen.queryByText(/Active version: manifest-default/)).not.toBeInTheDocument();
  });

  it("keeps activation declarations visible when cached provider reading fails and supports explicit reload", async () => {
    runtimeReadiness.mockRejectedValueOnce(new Error("Runtime unavailable"));
    render(<AgentRuntimeReadiness {...props} />);
    open();
    expect(await screen.findByText("Runtime unavailable")).toBeVisible();
    screen.getByText("Specialist activation declarations").closest("details")!.open = true;
    expect(screen.getByText("Network agent")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reload cached provider report" }));
    expect(await screen.findByText("Snapshot is old")).toBeVisible();
    expect(runtimeReadiness).toHaveBeenCalledTimes(2);
  });

  it("shows independent cached observations despite catalog failure", async () => {
    render(<AgentRuntimeReadiness {...props} agents={[]} catalogError="Catalog unavailable" />);
    open();
    expect(await screen.findByText("Snapshot is old")).toBeVisible();
    screen.getByText("Specialist activation declarations").closest("details")!.open = true;
    expect(screen.getByText("Catalog unavailable")).toBeVisible();
  });

  it("shows no-declaration and absent-source-time states without inventing freshness", async () => {
    runtimeReadiness.mockResolvedValueOnce(envelope({ ...report, providers: {
      copilot: { ...report.providers.network!, state: "disabled", freshness: "", ontology_version: "", last_success_at: "", last_attempt_at: "" },
    } }));
    render(<AgentRuntimeReadiness {...props} agents={[]} />);
    open();
    expect(await screen.findByText("disabled")).toBeVisible();
    screen.getByText("Specialist activation declarations").closest("details")!.open = true;
    expect(screen.getByText("No specialist activation metadata")).toBeVisible();
    expect(screen.getByText(/Last successful load: Not reported/)).toBeVisible();
    expect(screen.getByText(/Source freshness: Not reported/)).toBeVisible();
  });

  it("labels only declared active versions, not inactive candidate versions", async () => {
    render(<AgentRuntimeReadiness {...props} agents={[{ ...agents[0], foundry: {
      ...agents[0].foundry!, configured: true, status: "active", version: "exact-active-version",
    } }]} />);
    open();
    const activeVersion = await screen.findByText(/Active version: exact-active-version/);
    screen.getByText("Specialist activation declarations").closest("details")!.open = true;
    expect(activeVersion).toBeVisible();
    expect(screen.getByText(/provider version provider-version-1/)).toBeVisible();
  });

  it("aborts and discards observations after scope replacement", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    runtimeReadiness.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const view = render(<AgentRuntimeReadiness {...props} scope={{ subscription: ["old"] }} />);
    open();
    await waitFor(() => expect(runtimeReadiness).toHaveBeenCalledOnce());
    const signal = runtimeReadiness.mock.calls[0][1].signal as AbortSignal;
    view.rerender(<AgentRuntimeReadiness {...props} scope={{ subscription: ["new"] }} />);
    expect(await screen.findByText("Snapshot is old")).toBeVisible();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope({ ...report, providers: { secret_old_scope: null } })));
    expect(screen.queryByText("secret_old_scope")).not.toBeInTheDocument();
  });

  it("keeps absent boolean declarations unknown rather than false", async () => {
    runtimeReadiness.mockResolvedValueOnce(envelope({ ...report, providers: {
      copilot: { ...report.providers.network!, configured: null, loaded: null, cache_key_stale: null },
    } }));
    render(<AgentRuntimeReadiness {...props} />);
    open();
    expect(await screen.findByText(/Configured: Not reported. Loaded: Not reported. Cache key changed: Not reported/)).toBeVisible();
  });
});
