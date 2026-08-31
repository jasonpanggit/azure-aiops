import { describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TablePagination } from "./TablePagination";
import { TableColumnFilters } from "./TableColumnFilters";
import { useTablePagination } from "@/lib/use-table-pagination";

const rows = Array.from({ length: 250 }, (_, index) => index);

describe("useTablePagination", () => {
  it("defaults to 20 rows per page", () => {
    const { result } = renderHook(() => useTablePagination(rows));
    expect(result.current.pageSize).toBe(20);
    expect(result.current.pageRows).toHaveLength(20);
    expect(result.current.pageRows[0]).toBe(0);
    expect(result.current.total).toBe(250);
    expect(result.current.pageCount).toBe(13);
  });

  it("jumps to an arbitrary page", () => {
    const { result } = renderHook(() => useTablePagination(rows));
    act(() => result.current.setPage(5));
    expect(result.current.pageRows[0]).toBe(100);
  });

  it("keeps the first visible row when the page size changes", () => {
    const { result } = renderHook(() => useTablePagination(rows));
    act(() => result.current.setPage(4)); // rows 80..99
    act(() => result.current.setPageSize(50));
    expect(result.current.pageSize).toBe(50);
    // Row 80 must remain on screen rather than jumping to an unrelated offset.
    expect(result.current.pageRows[0]).toBe(50);
    expect(result.current.pageRows).toContain(80);
  });

  it("clamps the page when filtering shrinks the row set", () => {
    const { result, rerender } = renderHook(({ data }) => useTablePagination(data), {
      initialProps: { data: rows },
    });
    act(() => result.current.setPage(10));
    rerender({ data: rows.slice(0, 25) });
    expect(result.current.page).toBe(1);
    expect(result.current.pageRows).toHaveLength(5);
  });
});

describe("TablePagination", () => {
  it("renders the range summary and page size options", () => {
    render(
      <TablePagination
        total={250}
        pageRows={20}
        page={0}
        onPageChange={() => {}}
        pageSize={20}
        onPageSizeChange={() => {}}
        label="servers"
      />,
    );
    expect(screen.getByText(/Showing 1–20 of 250 servers/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /rows per page for servers/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "50 / page" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "100 / page" })).toBeInTheDocument();
  });

  it("lets an operator jump straight to a page", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(
      <TablePagination
        total={250}
        pageRows={20}
        page={0}
        onPageChange={onPageChange}
        pageSize={20}
        onPageSizeChange={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Page 13" }));
    expect(onPageChange).toHaveBeenCalledWith(12);
  });

  it("marks the current page and disables Previous on the first page", () => {
    render(
      <TablePagination
        total={250}
        pageRows={20}
        page={0}
        onPageChange={() => {}}
        pageSize={20}
        onPageSizeChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
  });

  it("keeps the total visible but drops controls for a single page", () => {
    render(
      <TablePagination
        total={4}
        pageRows={4}
        page={0}
        onPageChange={() => {}}
        pageSize={20}
        onPageSizeChange={() => {}}
        label="rows"
      />,
    );
    expect(screen.getByText(/Showing 1–4 of 4 rows/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  });

  it("uses the server envelope offset when one is supplied", () => {
    render(
      <TablePagination
        pagination={{ offset: 40, limit: 20, total: 250, next_offset: 60 }}
        pageRows={20}
        page={2}
        onPageChange={() => {}}
        label="installations"
      />,
    );
    expect(screen.getByText(/Showing 41–60 of 250 installations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
  });
});

describe("TableColumnFilters", () => {
  it("renders column filters and result counts", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <TableColumnFilters
        totalCount={12}
        resultCount={3}
        filters={[
          {
            id: "provider",
            label: "Provider column",
            value: "Compute",
            allLabel: "All providers",
            options: [
              { value: "Compute", label: "Compute" },
              { value: "Network", label: "Network" },
            ],
            onChange,
          },
        ]}
      />,
    );

    expect(screen.getByText("3 of 12 shown")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: /filter by provider column/i }), "Network");
    expect(onChange).toHaveBeenCalledWith("Network");
  });

  it("only shows reset when a column filter is active", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    const { rerender } = render(
      <TableColumnFilters
        onReset={onReset}
        filters={[{ id: "source", label: "Source column", value: "all", options: [] }]}
      />,
    );

    expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();

    rerender(
      <TableColumnFilters
        onReset={onReset}
        filters={[{ id: "source", label: "Source column", value: "arc", options: [{ value: "arc", label: "Arc" }] }]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
