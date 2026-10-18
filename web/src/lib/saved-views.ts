import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";

export type SearchViewSettings = {
  kind: "search";
  query: string;
  entity_type: string;
  source: string;
};
export type SituationViewSettings = {
  kind: "situations";
  query: string;
  priority: "all" | "P1" | "P2" | "P3";
  assigned_owner: string;
  lifecycle_state: string;
  older_than_hours: 24 | 168 | 720 | null;
  sort: "default" | "oldest" | "newest";
  response_deadline?: "" | "due" | "overdue" | "unknown" | "closed";
};
export type SavedViewSettings = SearchViewSettings | SituationViewSettings;
export type SavedView = SavedViewSettings & { view_id: string; name: string };
export interface SavedViewCollection {
  schema_version: 1;
  actor: string;
  scope: Record<string, string[]>;
  revision: number;
  updated_at: string;
  views: SavedView[];
}

/** Restore only allowlisted first-page settings and the current exact scope, never a stored URL. */
export function savedViewHref(view: SavedViewSettings, scope: ScopeSelection): string {
  const params = scopeToSearchParams(scope);
  if (view.query) params.set("q", view.query);
  if (view.kind === "search") {
    if (view.entity_type) params.set("entity_type", view.entity_type);
    if (view.source) params.set("source", view.source);
  } else {
    if (view.priority !== "all") params.set("priority", view.priority);
    if (view.assigned_owner) params.set("assigned_owner", view.assigned_owner);
    if (view.lifecycle_state) params.set("lifecycle_state", view.lifecycle_state);
    if (view.older_than_hours !== null) params.set("older_than_hours", String(view.older_than_hours));
    if (view.sort !== "default") params.set("sort", view.sort);
    if (view.response_deadline) params.set("response_deadline", view.response_deadline);
  }
  return `/${view.kind}${params.size ? `?${params}` : ""}`;
}
