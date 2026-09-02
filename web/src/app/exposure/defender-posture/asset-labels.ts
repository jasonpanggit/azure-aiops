import type { DefenderPostureFinding } from "@/lib/types";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  "microsoft.resources/subscriptions": "Subscription",
  "microsoft.resources/subscriptions/resourcegroups": "Resource group",
  "microsoft.compute/virtualmachines": "Virtual machine",
  "microsoft.hybridcompute/machines": "Arc-enabled server",
  "microsoft.app/containerapps": "Container app",
  "microsoft.containerservice/managedclusters": "AKS cluster",
  "microsoft.containerregistry/registries": "Container registry",
  "microsoft.storage/storageaccounts": "Storage account",
  "microsoft.web/sites": "App Service",
  "microsoft.keyvault/vaults": "Key Vault",
  "microsoft.sql/servers/databases": "SQL database",
  "microsoft.sql/servers": "SQL server",
};

export function formatDefenderAsset(rec: DefenderPostureFinding) {
  const resourceType = rec.resource_type || resourceTypeFromArmId(rec.asset_id);
  const typeLabel = friendlyResourceType(resourceType);
  const inventoryLabel = rec.inventory_kind && rec.inventory_kind !== "Azure resource" ? rec.inventory_kind : typeLabel;
  const assetName = displayResourceName(rec.asset_name, rec.asset_id, typeLabel);
  return `${assetName} (${inventoryLabel})`;
}

function displayResourceName(assetName: string, assetId: string, typeLabel: string) {
  const cleanedName = assetName.trim();
  const armName = resourceNameFromArmId(assetId);
  if (!cleanedName || UUID_PATTERN.test(cleanedName)) {
    return typeLabel === "Subscription" && (armName || cleanedName)
      ? `Subscription ${armName || cleanedName}`
      : armName || cleanedName || "Unknown asset";
  }
  return collapseDuplicatedContainerName(cleanedName);
}

function collapseDuplicatedContainerName(value: string) {
  const parts = value.split("___");
  return parts.length === 2 && parts[0] === parts[1] ? parts[0] : value;
}

function friendlyResourceType(resourceType: string) {
  const normalized = resourceType.trim().toLowerCase();
  if (!normalized) {
    return "Azure resource";
  }
  if (RESOURCE_TYPE_LABELS[normalized]) {
    return RESOURCE_TYPE_LABELS[normalized];
  }
  const lastSegment = resourceType.trim().split("/").at(-1) || normalized;
  return lastSegment
    .replace(/([a-z])([A-Z0-9])/g, "$1 $2")
    .replace(/([0-9])([a-zA-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function resourceNameFromArmId(resourceId: string) {
  const parts = resourceIdParts(resourceId);
  if (parts.length >= 2 && parts[0].toLowerCase() === "subscriptions") {
    return parts.length === 2 ? parts[1] : parts.at(-1) || "";
  }
  return parts.at(-1) || "";
}

function resourceTypeFromArmId(resourceId: string) {
  const parts = resourceIdParts(resourceId);
  if (parts.length === 2 && parts[0].toLowerCase() === "subscriptions") {
    return "microsoft.resources/subscriptions";
  }
  const providersIndex = parts.findIndex((part) => part.toLowerCase() === "providers");
  if (providersIndex === -1 || providersIndex + 2 >= parts.length) {
    return "";
  }
  const providerAndTail = parts.slice(providersIndex + 1);
  return [providerAndTail[0], ...providerAndTail.slice(1).filter((_, index) => index % 2 === 0)].join("/");
}

function resourceIdParts(resourceId: string) {
  return resourceId.split("/").filter(Boolean);
}
