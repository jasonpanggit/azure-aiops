import { scopeToSearchParams, type ScopeSelection } from "./scope";
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from "./use-table-pagination";

/** Parse an explicit grouped-inventory bookmark without silently repairing it. */
export function parseInventoryView(params: URLSearchParams) {
  function text(key: string, fallback = "", max = 256) {
    const value = params.get(key) ?? fallback;
    if (value.length > max || /[\u0000-\u001f\u007f]/.test(value)) {
      throw new Error(`Invalid inventory bookmark field: ${key}`);
    }
    return value;
  }
  function choice<T extends string>(key: string, values: readonly T[], fallback: T): T {
    const value = params.get(key) ?? fallback;
    const selected = values.find(item => item === value);
    if (!selected) throw new Error(`Invalid inventory bookmark field: ${key}`);
    return selected;
  }
  function number(key: string, fallback: number, size = false): number {
    const value = params.get(key);
    if (value === null) return fallback;
    const parsed = Number(value);
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(parsed) || parsed > 10_000 ||
      (size && !PAGE_SIZE_OPTIONS.some(option => option === parsed))) {
      throw new Error(`Invalid inventory bookmark field: ${key}`);
    }
    return parsed;
  }
  const exportId = text("export_id", "", 36);
  const rawOffset = params.get("export_offset") ?? "0";
  const exportOffset = Number(rawOffset);
  if ((exportId && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(exportId)) ||
    !/^\d+$/.test(rawOffset) || !Number.isSafeInteger(exportOffset) || exportOffset > 49_500 ||
    exportOffset % 500 !== 0 || (!exportId && params.has("export_offset"))) {
    throw new Error("Invalid inventory export bookmark.");
  }
  return {
    tab: choice("tab", ["os", "software", "azure"], "os"),
    subscriptionFilter: text("subscriptionFilter", "all"),
    search: text("search"),
    sourceFilter: choice("sourceFilter", ["all", "azure_vm", "arc"], "all"),
    lifecycleFilter: choice("lifecycleFilter", ["all", "expired", "expiring", "supported", "review"], "all"),
    osNameFilter: text("osNameFilter", "all", 120),
    osVersionFilter: text("osVersionFilter", "all", 120),
    softwareSearch: text("softwareSearch"),
    softwareSourceFilter: choice("softwareSourceFilter", ["all", "azure_vm", "arc", "unlinked"], "all"),
    softwareNameFilter: text("softwareNameFilter", "all"),
    softwarePublisherFilter: text("softwarePublisherFilter", "all"),
    azureSearch: text("azureSearch"),
    azureProviderFilter: text("azureProviderFilter", "all"),
    azureTypeFilter: text("azureTypeFilter", "all"),
    azureSkuFilter: text("azureSkuFilter", "all"),
    osPage: number("osPage", 0), softwarePage: number("softwarePage", 0), azurePage: number("azurePage", 0),
    osPageSize: number("osPageSize", DEFAULT_PAGE_SIZE, true),
    softwarePageSize: number("softwarePageSize", DEFAULT_PAGE_SIZE, true),
    azurePageSize: number("azurePageSize", DEFAULT_PAGE_SIZE, true),
    export_id: exportId, export_offset: exportOffset,
  };
}

export type InventoryView = ReturnType<typeof parseInventoryView>;

/** Serialize only reviewed view fields plus the current caller-selected scope. */
export function inventoryViewQuery(view: InventoryView, scope: ScopeSelection): URLSearchParams {
  const params = scopeToSearchParams(scope);
  const defaults = new Map(Object.entries(parseInventoryView(new URLSearchParams())));
  for (const [key, value] of Object.entries(view)) {
    if (value !== defaults.get(key)) params.set(key, String(value));
  }
  return params;
}
