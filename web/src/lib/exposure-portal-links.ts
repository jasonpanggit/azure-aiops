export const DEFENDER_PORTAL_ACTION_LABELS = {
  open_defender_alert: "Open alert in Defender for Cloud",
  open_defender_attack_path: "Open attack path in Defender for Cloud",
  open_defender_recommendation: "Open recommendation in Defender for Cloud",
  open_azure_resource: "Open affected resource in Azure portal",
  open_registry: "Open registry in Azure portal",
  open_cluster: "Open cluster in Azure portal",
} as const;

export type DefenderPortalActionKind =
  keyof typeof DEFENDER_PORTAL_ACTION_LABELS;

export interface DefenderPortalAction {
  kind: DefenderPortalActionKind;
  /** Complete destination supplied by the governed backend. */
  href?: string | null;
  /** Canonical backend-authorized ARM ID for resource actions. */
  resourceId?: string | null;
  evidenceId?: string | null;
  disabledReason?: string | null;
}

const DEFENDER_ROUTE_PREFIXES: Record<
  Extract<
    DefenderPortalActionKind,
    | "open_defender_alert"
    | "open_defender_attack_path"
    | "open_defender_recommendation"
  >,
  readonly string[]
> = {
  open_defender_alert: [
    "view/Microsoft_Azure_Security/AlertBlade/",
    "blade/Microsoft_Azure_Security/AlertBlade/",
  ],
  open_defender_attack_path: [
    "view/Microsoft_Azure_Security/AttackPathBlade/",
    "blade/Microsoft_Azure_Security/AttackPathBlade/",
  ],
  open_defender_recommendation: [
    "view/Microsoft_Azure_Security/RecommendationBlade/",
    "view/Microsoft_Azure_Security/RecommendationsBlade/",
    "blade/Microsoft_Azure_Security/RecommendationBlade/",
    "blade/Microsoft_Azure_Security/RecommendationsBlade/",
  ],
};

const RESOURCE_ACTIONS = new Set<DefenderPortalActionKind>([
  "open_azure_resource",
  "open_registry",
  "open_cluster",
]);

const CONTROL_OR_SLASH_PATTERN = /[\u0000-\u001f\u007f\\]/;

function decodedPortalRoute(hash: string): string | null {
  if (!hash.startsWith("#") || hash.length === 1) return null;
  try {
    const decoded = decodeURIComponent(hash.slice(1)).replace(/^\/+/, "");
    if (
      !decoded ||
      CONTROL_OR_SLASH_PATTERN.test(decoded) ||
      decoded.includes("?") ||
      decoded.includes("#") ||
      decoded.split("/").some((segment) => segment === "." || segment === "..")
    ) {
      return null;
    }
    return decoded;
  } catch {
    return null;
  }
}

function normalizedArmId(value: string | null | undefined): string | null {
  const trimmed = value?.trim().replace(/\/+$/, "") ?? "";
  if (!trimmed || CONTROL_OR_SLASH_PATTERN.test(trimmed)) return null;
  const segments = trimmed.split("/").filter(Boolean);
  if (
    segments.length < 2 ||
    segments[0].toLocaleLowerCase("en-US") !== "subscriptions" ||
    segments.some((segment) => segment === "." || segment === "..")
  ) {
    return null;
  }
  if (
    segments.length > 2 &&
    (segments.length < 4 ||
      segments[2].toLocaleLowerCase("en-US") !== "resourcegroups")
  ) {
    return null;
  }
  if (
    segments.length > 4 &&
    (segments.length < 8 ||
      segments[4].toLocaleLowerCase("en-US") !== "providers" ||
      (segments.length - 6) % 2 !== 0)
  ) {
    return null;
  }
  return `/${segments.join("/")}`.toLocaleLowerCase("en-US");
}

function resourceIdFromRoute(
  route: string,
  expectedResourceId: string,
): string | null {
  const marker = route.startsWith("resource/")
    ? "resource/"
    : route.match(/^@[^/]+\/resource\//)?.[0];
  if (!marker) return null;
  const routeResource = `/${route.slice(marker.length)}`.replace(/\/+$/, "");
  const expected = normalizedArmId(expectedResourceId);
  if (!expected) return null;

  const candidates = [
    routeResource,
    routeResource.replace(/\/overview$/i, ""),
  ];
  return candidates.find((candidate) => normalizedArmId(candidate) === expected)
    ? expected
    : null;
}

function resourceKindMatches(
  kind: DefenderPortalActionKind,
  normalizedResourceId: string,
): boolean {
  if (kind === "open_registry") {
    return normalizedResourceId.includes(
      "/providers/microsoft.containerregistry/registries/",
    );
  }
  if (kind === "open_cluster") {
    return normalizedResourceId.includes(
      "/providers/microsoft.containerservice/managedclusters/",
    );
  }
  return kind === "open_azure_resource";
}

/**
 * Validate a complete, backend-issued Azure portal destination.
 *
 * This helper deliberately never constructs portal URLs. Resource links must
 * carry the exact canonical ARM ID already present in the authorized result,
 * and Defender links are bound to the blade selected by their closed kind.
 */
export function safeDefenderPortalHref(
  action: DefenderPortalAction,
  authorizedResourceIds: readonly string[] = [],
): string | null {
  if (!action.href) return null;
  let url: URL;
  try {
    url = new URL(action.href);
  } catch {
    return null;
  }
  if (
    url.protocol !== "https:" ||
    url.hostname.toLocaleLowerCase("en-US") !== "portal.azure.com" ||
    url.username ||
    url.password ||
    url.port ||
    (url.pathname !== "/" && url.pathname !== "") ||
    url.search
  ) {
    return null;
  }

  const route = decodedPortalRoute(url.hash);
  if (!route) return null;

  if (!RESOURCE_ACTIONS.has(action.kind)) {
    const prefixes =
      DEFENDER_ROUTE_PREFIXES[
        action.kind as keyof typeof DEFENDER_ROUTE_PREFIXES
      ];
    return prefixes?.some(
      (prefix) => route.startsWith(prefix) && route.length > prefix.length,
    )
      ? action.href
      : null;
  }

  const expectedResourceId = action.resourceId?.trim() ?? "";
  const normalizedExpected = normalizedArmId(expectedResourceId);
  if (!normalizedExpected) return null;
  const authorized = new Set(
    authorizedResourceIds
      .map((resourceId) => normalizedArmId(resourceId))
      .filter((resourceId): resourceId is string => resourceId !== null),
  );
  if (!authorized.has(normalizedExpected)) return null;

  const routedResourceId = resourceIdFromRoute(route, expectedResourceId);
  if (
    !routedResourceId ||
    !resourceKindMatches(action.kind, routedResourceId)
  ) {
    return null;
  }
  return action.href;
}

/** Accept only a backend-projected, same-origin remediation workspace path. */
export function safeGovernedHandoffHref(
  href: string | null | undefined,
): string | null {
  const trimmed = href?.trim() ?? "";
  if (
    !trimmed.startsWith("/") ||
    trimmed.startsWith("//") ||
    CONTROL_OR_SLASH_PATTERN.test(trimmed)
  ) {
    return null;
  }
  try {
    const parsed = new URL(trimmed, "https://exposure.local");
    return parsed.origin === "https://exposure.local" &&
      parsed.pathname === "/remediation"
      ? `${parsed.pathname}${parsed.search}${parsed.hash}`
      : null;
  } catch {
    return null;
  }
}
