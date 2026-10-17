import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Envelope, FabricDatasetContract as Contract } from "@/lib/types";
import { FabricDatasetContract } from "./FabricDatasetContract";

const { read } = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("@/lib/services", () => ({ fabricMedallionApi: { datasetContract: read } }));
const scope = { subscription: ["sub-a"], subscription_connection: ["conn-one"], environment: ["prod"] };

function fixture(tableName = "bronze_resources"): Envelope<Contract> {
  return {
    scope, evidence: [], data: {
      table_name: tableName, evaluated_at: "2026-10-17T12:00:00Z",
      declared_schema: { source: "fabric.schema_registry", version: "2.7.0", status: "available",
        fields: [{ name: "resource_id", type: "string", nullable: false }] },
      deployed_schema_validation: "not_collected", producer_ownership: "not_collected", dataset_dependency_graph: "not_collected",
      source_diagnostics: [{ scope, partition_key: "part-a", status_at: "2026-10-17T10:00:00Z",
        freshness: "stale", recorded_status: "failed", recorded_quality: "degraded",
        lineage_ref: "bronze_resources-table", issues: ["source_failed", "freshness_stale"] }],
    },
  };
}

function renderContract() {
  return render(<FabricDatasetContract tableName="bronze_resources" scope={scope} refreshKey={0} id="contract-test" onClose={vi.fn()} />);
}

describe("Declared Fabric dataset contract", () => {
  beforeEach(() => { read.mockReset(); read.mockResolvedValue(fixture()); });

  it("loads exactly scoped registry fields and qualifies diagnostics without claiming schema validation or edges", async () => {
    renderContract();
    expect(await screen.findByRole("table")).toHaveAccessibleName("bronze_resources: 1 declared fields");
    expect(read).toHaveBeenCalledWith("bronze_resources", scope);
    expect(screen.getByRole("row", { name: "resource_id string No" })).toBeInTheDocument();
    expect(screen.getByText(/Deployed-schema validation and producer ownership are not collected/)).toBeInTheDocument();
    expect(screen.getByText(/Dataset dependency edges are not collected/)).toBeInTheDocument();
    expect(screen.getByText("Source attempt recorded failed · Metadata clock past target")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Dataset contract: bronze_resources" })).toHaveFocus();
  });

  it("distinguishes an absent registry contract from an empty deployed table", async () => {
    const value = fixture();
    value.data.declared_schema.status = "not_registered";
    value.data.declared_schema.fields = [];
    read.mockResolvedValue(value);
    renderContract();
    expect(await screen.findByText("No declared schema registered")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/does not prove the deployed table has no schema/)).toBeInTheDocument();
  });

  it.each(["wrong-dataset", "invalid-nullability", "invalid-schema-state"])("rejects inconsistent contract: %s", async reason => {
    const value = fixture();
    if (reason === "wrong-dataset") value.data.table_name = "gold_hidden";
    if (reason === "invalid-nullability") Object.assign(value.data.declared_schema.fields[0], { nullable: "false" });
    if (reason === "invalid-schema-state") Object.assign(value.data.declared_schema, { status: "verified" });
    read.mockResolvedValue(value);
    renderContract();
    expect(await screen.findByText("Dataset contract unavailable")).toBeInTheDocument();
    expect(screen.getByText(/inconsistent with the requested dataset/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("exposes an explicit retry after a failed read without replaying any mutation", async () => {
    read.mockRejectedValueOnce(new Error("Synthetic read failure"));
    renderContract();
    expect(await screen.findByText("Synthetic read failure")).toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry contract read" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("paginates fields and diagnostics independently without refetching evidence", async () => {
    const value = fixture();
    value.data.declared_schema.fields = Array.from({ length: 21 }, (_, index) => ({ name: `field_${index}`, type: "string", nullable: false }));
    value.data.source_diagnostics = Array.from({ length: 21 }, (_, index) => ({ ...value.data.source_diagnostics[0], partition_key: `partition-${index}` }));
    read.mockResolvedValue(value);
    renderContract();
    const table = await screen.findByRole("table");
    expect(within(table).queryByText("field_20")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Rows per page for declared fields"), { target: { value: "50" } });
    expect(within(table).getByText("field_20")).toBeInTheDocument();
    expect(screen.queryByText("Source partition: partition-20")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Rows per page for source diagnostics"), { target: { value: "50" } });
    expect(screen.getByText("Source partition: partition-20")).toBeInTheDocument();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("ignores a late result from a previous dataset identity", async () => {
    let release = () => {};
    read.mockReturnValueOnce(new Promise(resolve => { release = () => resolve(fixture()); }));
    read.mockResolvedValue(fixture("gold_custom"));
    const view = renderContract();
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    view.rerender(<FabricDatasetContract tableName="gold_custom" scope={scope} refreshKey={0} id="contract-test" onClose={vi.fn()} />);
    expect(await screen.findByRole("table", { name: "gold_custom: 1 declared fields" })).toBeInTheDocument();
    await act(async () => release());
    expect(screen.queryByRole("table", { name: "bronze_resources: 1 declared fields" })).not.toBeInTheDocument();
  });
});
