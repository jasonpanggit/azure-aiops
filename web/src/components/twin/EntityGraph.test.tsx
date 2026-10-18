import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TwinSnapshot } from "@/lib/types";
import { EntityGraph } from "./EntityGraph";

function graph(count = 4): TwinSnapshot {
  return {
    twin_id: "operational-twin", version: "fixture", previous_version: null,
    observed_at: "2026-10-16T12:00:00Z", scope: {}, confidence: "medium", provenance: [], timeline: [],
    temporal: { current_state_version: "fixture", previous_state_version: null, change_history: [], risk_trend: [], dependency_evolution: [] },
    entities: Array.from({ length: count }, (_, index) => ({
      id: index === 1 ? "business_service:payments" : `resource:vm-${index}`,
      name: index === 1 ? "Payments" : `Worker ${index}`,
      kind: index === 1 ? "business_service" : "resource",
      version: `entity-${index}`, state: "current", confidence: "high", provenance: [], properties: {},
    })),
    relationships: Array.from({ length: count - 1 }, (_, index) => ({
      id: `relationship-${index}`, source: "resource:vm-0",
      target: index === 0 ? "business_service:payments" : `resource:vm-${index + 1}`,
      type: "supports", confidence: "high", provenance: [],
    })),
  };
}

describe("Twin entity explorer", () => {
  it("does not choose a node or run resource review implicitly", () => {
    const select = vi.fn();
    render(<EntityGraph snapshot={graph()} onSelectResource={select} />);
    expect(screen.getByText(/Nothing is selected automatically/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Scrollable entity graph" })).not.toBeInTheDocument();
    expect(select).not.toHaveBeenCalled();
  });

  it("searches names and exact identity text, filters kinds, clears filters and discloses no matches", () => {
    render(<EntityGraph snapshot={graph()} onSelectResource={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Find entity"), { target: { value: "PAYMENTS" } });
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 1 matches in 4 loaded entities");
    expect(within(screen.getByRole("group", { name: "Matching entities" })).getAllByRole("button")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Entity type"), { target: { value: "resource" } });
    expect(screen.getByText(/No entities match/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear entity filters" }));
    fireEvent.change(screen.getByLabelText("Find entity"), { target: { value: "resource:vm-2" } });
    expect(screen.getByRole("button", { name: "Explore Worker 2, resource:vm-2" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 1");
  });

  it("draws actual links, follows a neighbor by keyboard and requires a separate resource-review action", () => {
    const select = vi.fn();
    render(<EntityGraph snapshot={graph()} onSelectResource={select} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore Payments, business_service:payments" }));
    const canvas = screen.getByRole("region", { name: "Scrollable entity graph" });
    expect(canvas.querySelectorAll("line")).toHaveLength(1);
    expect(canvas).toHaveAttribute("tabindex", "0");
    const worker = screen.getByRole("button", { name: "Graph node Worker 0, resource" });
    fireEvent.keyDown(worker, { key: "Enter" });
    expect(screen.getByRole("group", { name: "Linked neighborhood of Worker 0" })).toBeInTheDocument();
    expect(canvas.querySelectorAll("line")).toHaveLength(3);
    expect(select).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Use focused resource for review" }));
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith("resource:vm-0");
    fireEvent.keyDown(screen.getByRole("button", { name: "Graph node Payments, business service" }), { key: " " });
    expect(screen.getByRole("group", { name: "Linked neighborhood of Payments" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use focused resource for review" })).not.toBeInTheDocument();
    expect(select).toHaveBeenCalledTimes(1);
  });

  it("enforces result, neighbor and parallel-edge limits without hiding their totals", () => {
    const snapshot = graph(50);
    snapshot.relationships.push(...Array.from({ length: 50 }, (_, index) => ({
      ...snapshot.relationships[0], id: `parallel-${index}`,
    })));
    render(<EntityGraph snapshot={snapshot} onSelectResource={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 30 of 50 matches");
    expect(within(screen.getByRole("group", { name: "Matching entities" })).getAllByRole("button")).toHaveLength(30);
    fireEvent.click(screen.getByRole("button", { name: "Explore Worker 0, resource:vm-0" }));
    expect(screen.getByText(/Showing 12 of 49 direct neighbors and 32 of 99 incident links/)).toBeInTheDocument();
    const canvas = screen.getByRole("region", { name: "Scrollable entity graph" });
    expect(within(canvas).getAllByRole("button")).toHaveLength(13);
    expect(canvas.querySelectorAll("line")).toHaveLength(32);
  });

  it("excludes dangling links and never substitutes inferred dependencies for absent mappings", () => {
    const snapshot = graph();
    snapshot.relationships = [{ ...snapshot.relationships[0], target: "resource:missing" }];
    render(<EntityGraph snapshot={snapshot} onSelectResource={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore Worker 0, resource:vm-0" }));
    expect(screen.getByText(/No confirmed links to other loaded entities/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Graph node.*missing/ })).not.toBeInTheDocument();
  });

  it("preserves a reported self-reference without inventing a neighboring node", () => {
    const snapshot = graph(1);
    snapshot.relationships = [{
      id: "self-link", source: "resource:vm-0", target: "resource:vm-0",
      type: "self_reference", confidence: "medium", provenance: [],
    }];
    render(<EntityGraph snapshot={snapshot} onSelectResource={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore Worker 0, resource:vm-0" }));
    const canvas = screen.getByRole("region", { name: "Scrollable entity graph" });
    expect(within(canvas).getAllByRole("button")).toHaveLength(1);
    expect(canvas.querySelectorAll("path.twin-entity-self-link")).toHaveLength(1);
    expect(screen.getByText(/Showing 0 of 0 direct neighbors and 1 of 1/)).toBeInTheDocument();
  });

  it("allows explicitly recentering a horizontally scrolled narrow graph", () => {
    render(<EntityGraph snapshot={graph()} onSelectResource={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore Worker 0, resource:vm-0" }));
    const canvas = screen.getByRole("region", { name: "Scrollable entity graph" });
    Object.defineProperty(canvas, "scrollWidth", { value: 740 });
    Object.defineProperty(canvas, "clientWidth", { value: 310 });
    canvas.scrollLeft = 0;
    fireEvent.click(screen.getByRole("button", { name: "Center focused node" }));
    expect(canvas.scrollLeft).toBe(215);
  });

  it("clears old focus when the page remounts for another snapshot or scope", () => {
    const { rerender } = render(<EntityGraph key="scope-a" snapshot={graph()} onSelectResource={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Explore Worker 0, resource:vm-0" }));
    const snapshot = graph(1);
    snapshot.entities = [{ ...snapshot.entities[0], id: "resource:other", name: "Other worker" }];
    rerender(<EntityGraph key="scope-b" snapshot={snapshot} onSelectResource={vi.fn()} />);
    expect(screen.queryByRole("group", { name: "Linked neighborhood of Worker 0" })).not.toBeInTheDocument();
    expect(screen.queryByText("Worker 0")).not.toBeInTheDocument();
    expect(screen.getByText(/Nothing is selected automatically/)).toBeInTheDocument();
  });
});
