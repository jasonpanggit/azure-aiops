import { describe, expect, it, vi } from "vitest";
import { downloadCsv, escapeCsvCell, serializeCsv } from "./csv";

describe("inventory CSV serialization", () => {
  it("quotes RFC-4180 delimiters and neutralizes spreadsheet formulas", () => {
    const csv = serializeCsv(
      [{
        identity: '=SUM("secret")',
        details: 'line one,\r\n"line two"',
        version: "-preview",
      }],
      ["identity", "details", "version"],
    );

    expect(csv).toBe(
      '"identity","details","version"\r\n' +
      `"'=SUM(""secret"")","line one,\r\n""line two""","'-preview"\r\n`,
    );
  });

  it("keeps numeric values intact while escaping quote characters", () => {
    expect(escapeCsvCell(42)).toBe('"42"');
    expect(escapeCsvCell(null)).toBe('""');
    expect(escapeCsvCell('say "hello"')).toBe('"say ""hello"""');
  });

  it.each([" =SUM(A1)", "\t=SUM(A1)", "\r@formula", "\n+formula", "  -formula", "\uFEFF=SUM(A1)"])(
    "neutralizes spreadsheet prefixes hidden behind whitespace: %j", value => {
      expect(escapeCsvCell(value)).toBe(`"'${value}"`);
    },
  );

  it("downloads only the supplied serialized rows", () => {
    const createObjectURL = vi.fn(() => "blob:inventory");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.fn();
    const link = {
      hidden: false,
      href: "",
      download: "",
      click,
      remove: vi.fn(),
    };
    const documentRef = {
      createElement: vi.fn(() => link),
      body: { appendChild: vi.fn() },
    } as unknown as Document;

    downloadCsv('"authorized"\r\n"row"\r\n', "inventory.csv", documentRef);

    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(link.download).toBe("inventory.csv");
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:inventory");
  });
});
