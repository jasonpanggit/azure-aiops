import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CopilotCitations, type CopilotCitation } from "./CopilotCitations";

function citation(
  citationId: string,
  source: string,
  observationStatus?: string,
): CopilotCitation {
  return {
    citation_id: citationId,
    source,
    status: "ok",
    observed_at: "2026-09-16T00:00:00Z",
    resource_id: "/subscriptions/sub-1",
    observation_status: observationStatus,
  };
}

describe("CopilotCitations", () => {
  it("starts collapsed with a count, expands, and collapses again", async () => {
    const user = userEvent.setup();
    render(
      <CopilotCitations
        ariaLabel="Investigation citations"
        citations={[
          citation("citation:one", "inventory/server", "historical"),
          citation("citation:two", "network/server", "current"),
        ]}
      />,
    );

    const toggle = screen.getByRole("button", { name: "Citations (2)" });
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    expect(screen.getByText("inventory/server")).toBeVisible();
    expect(screen.getByText("network/server")).toBeVisible();
    expect(screen.getAllByText("ok")).toHaveLength(2);

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
  });

  it("supports keyboard disclosure and exposes provenance when requested", async () => {
    const user = userEvent.setup();
    render(
      <CopilotCitations
        ariaLabel="Copilot citations"
        citations={[citation("citation:keyboard", "inventory/server", "revalidated")]}
      />,
    );

    await user.tab();
    const toggle = screen.getByRole("button", { name: "Citations (1)" });
    expect(toggle).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("citation:keyboard")).toBeVisible();
    expect(screen.getByText("/subscriptions/sub-1")).toBeVisible();
    expect(screen.getByText("2026-09-16T00:00:00Z")).toBeVisible();
    expect(screen.getByText("Revalidated evidence")).toBeVisible();
  });

  it("keeps disclosure state isolated and resets for a replacement answer", async () => {
    const user = userEvent.setup();
    const view = render(
      <>
        <CopilotCitations
          ariaLabel="First answer citations"
          citations={[citation("citation:first", "first/server")]}
        />
        <CopilotCitations
          ariaLabel="Second answer citations"
          citations={[citation("citation:second", "second/server")]}
        />
      </>,
    );

    const toggles = screen.getAllByRole("button", { name: "Citations (1)" });
    await user.click(toggles[0]);

    expect(toggles[0]).toHaveAttribute("aria-expanded", "true");
    expect(toggles[1]).toHaveAttribute("aria-expanded", "false");

    view.rerender(
      <CopilotCitations
        key="replacement-answer"
        ariaLabel="Replacement answer citations"
        citations={[citation("citation:first", "first/server")]}
      />,
    );
    expect(screen.getByRole("button", { name: "Citations (1)" }))
      .toHaveAttribute("aria-expanded", "false");
  });

  it("renders no disclosure for an answer without citations", () => {
    const { container } = render(
      <CopilotCitations ariaLabel="Copilot citations" citations={[]} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: /Citations/ })).not.toBeInTheDocument();
  });
});
