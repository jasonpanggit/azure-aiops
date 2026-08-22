import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SituationTable } from "@/components/SituationTable";
import { rankSituations } from "@/lib/situations";
import { createIncidentFixture } from "@/test/incident-fixture";

describe("SituationTable", () => {
  it("keeps priority, impact, likely cause, and owner visible in the queue", () => {
    render(<SituationTable situations={rankSituations([createIncidentFixture()])} />);

    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Payroll database latency" })).toHaveAttribute(
      "href",
      "/situations/INC-1001"
    );
    expect(screen.getByText("Payroll")).toBeInTheDocument();
    expect(screen.getByText("Database capacity exhausted after deployment")).toBeInTheDocument();
    expect(screen.getByText("Payroll Product")).toBeInTheDocument();
  });
});
