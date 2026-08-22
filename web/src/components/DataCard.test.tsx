import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataCard } from "@/components/DataCard";
import { ApiError } from "@/lib/types";

function renderWithTheme(node: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{node}</FluentProvider>);
}

describe("DataCard", () => {
  it("shows a loading spinner while loading", () => {
    renderWithTheme(
      <DataCard title="Test Tile" loading error={null}>
        <div>content</div>
      </DataCard>
    );
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders children when not loading and no error", () => {
    renderWithTheme(
      <DataCard title="Test Tile" loading={false} error={null}>
        <div>content</div>
      </DataCard>
    );
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("shows a roadmap-aware message for not-implemented endpoints instead of a blank tile", () => {
    const error = new ApiError(501, "not_implemented", "not implemented", { roadmap: "Prompt 16" });
    renderWithTheme(
      <DataCard title="Network Gaps" loading={false} error={error}>
        <div>content</div>
      </DataCard>
    );
    expect(screen.getByText(/Prompt 16/)).toBeInTheDocument();
    expect(screen.queryByText("content")).not.toBeInTheDocument();
  });

  it("shows the error message for an unexpected error", () => {
    renderWithTheme(
      <DataCard title="Test Tile" loading={false} error={new Error("boom")}>
        <div>content</div>
      </DataCard>
    );
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
