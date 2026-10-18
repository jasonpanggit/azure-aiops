/**
 * Small, dependency-free CSV boundary for bounded authorized exports.
 *
 * Every value is quoted for predictable RFC-4180 output. String cells that
 * could be interpreted as spreadsheet formulas are prefixed with an apostrophe
 * so an exported inventory value remains data when opened in a spreadsheet.
 */

export type CsvCell = string | number | boolean | null | undefined;

const FORMULA_LEADING = /^(?:[\t\r\n]|\s*[=+\-@])/;

export function serializeCsv(
  rows: readonly Record<string, CsvCell>[],
  columns: readonly string[],
): string {
  const records = [
    columns.map(escapeCsvCell),
    ...rows.map((row) => columns.map((column) => escapeCsvCell(row[column]))),
  ];
  return `${records.map((record) => record.join(",")).join("\r\n")}\r\n`;
}

export function escapeCsvCell(value: CsvCell): string {
  if (value === null || value === undefined) return '""';
  const text = typeof value === "string" && FORMULA_LEADING.test(value)
    ? `'${value}`
    : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

export function downloadCsv(
  csv: string,
  filename: string,
  documentRef: Document = document,
): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = documentRef.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  documentRef.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
