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

export type DefenderAssetIcon =
  | "server"
  | "container-image"
  | "registry"
  | "cluster"
  | "resource"
  | "mixed"
  | "unknown";

export interface DefenderAssetInput {
  assetId: string;
  assetName: string;
  resourceType: string;
  inventoryKind: string;
}

export interface DefenderAssetPresentation {
  label: string;
  kindLabel: string;
  icon: DefenderAssetIcon;
  serverActionEligible: boolean;
}

export function defenderAssetPresentation({
  assetId,
  assetName,
  resourceType: providedResourceType,
  inventoryKind,
}: DefenderAssetInput): DefenderAssetPresentation {
  const resourceType = providedResourceType || resourceTypeFromArmId(assetId);
  const typeLabel = friendlyResourceType(resourceType);
  const inventoryLabel =
    inventoryKind && inventoryKind !== "Azure resource"
      ? inventoryKind
      : typeLabel;
  const displayName = displayResourceName(assetName, assetId, typeLabel);
  const classification = classifyAsset(
    assetId,
    resourceType,
    inventoryKind,
  );
  return {
    label: `${displayName} (${inventoryLabel})`,
    ...classification,
  };
}

export function formatDefenderAsset(rec: DefenderPostureFinding) {
  return defenderAssetPresentation({
    assetId: rec.asset_id,
    assetName: rec.asset_name,
    resourceType: rec.resource_type,
    inventoryKind: rec.inventory_kind,
  }).label;
}

function classifyAsset(
  assetId: string,
  resourceType: string,
  inventoryKind: string,
): Omit<DefenderAssetPresentation, "label"> {
  const identity = `${resourceType} ${inventoryKind}`.toLocaleLowerCase(
    "en-US",
  );
  const mixed =
    identity.includes("mixed") ||
    identity.includes("+") ||
    ((identity.includes("server") || identity.includes("virtual machine")) &&
      identity.includes("container"));
  if (mixed) {
    return {
      kindLabel: "Mixed asset",
      icon: "mixed",
      serverActionEligible: false,
    };
  }
  if (
    identity.includes("containerimage") ||
    identity.includes("container image") ||
    identity.includes("container workload") ||
    assetId.toLocaleLowerCase("en-US").startsWith("sha256:")
  ) {
    return {
      kindLabel: "Container image",
      icon: "container-image",
      serverActionEligible: false,
    };
  }
  if (
    identity.includes("microsoft.containerregistry/registries") ||
    identity.includes("container registry")
  ) {
    return {
      kindLabel: "Container registry",
      icon: "registry",
      serverActionEligible: false,
    };
  }
  if (
    identity.includes("microsoft.containerservice/managedclusters") ||
    identity.includes("aks cluster")
  ) {
    return {
      kindLabel: "AKS cluster",
      icon: "cluster",
      serverActionEligible: false,
    };
  }
  if (
    identity.includes("microsoft.compute/virtualmachines") ||
    identity.includes("microsoft.hybridcompute/machines") ||
    identity.includes("server") ||
    identity.includes("virtual machine") ||
    identity.includes("azure vm") ||
    identity.includes("arc-enabled")
  ) {
    return {
      kindLabel: "Server",
      icon: "server",
      serverActionEligible: true,
    };
  }
  if (!resourceType.trim() && !inventoryKind.trim()) {
    return {
      kindLabel: "Unknown asset",
      icon: "unknown",
      serverActionEligible: false,
    };
  }
  return {
    kindLabel: typeLabelForUnknown(resourceType),
    icon: "resource",
    serverActionEligible: false,
  };
}

function typeLabelForUnknown(resourceType: string) {
  const label = friendlyResourceType(resourceType);
  return label === "Azure resource" ? "Unknown asset" : label;
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
