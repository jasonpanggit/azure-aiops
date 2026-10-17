import { apiRequest } from "./api-client";
import { scopeToSearchParams, type ScopeSelection } from "./scope";

/** Team navigation state only; no provider result or execution authority. */
export interface InvestigationWorkspaceView {
  title: string;
  entry_type: "BusinessService" | "Application" | "Environment" | "SubscriptionConnection" | "Incident" | "CVE" | "NetworkGap" | "RemediationPlan";
  subject: string;
  mode: "executive" | "engineer";
}

/** Immutable server-attributed navigation and membership revision. */
export interface InvestigationWorkspaceRevision {
  revision: number;
  actor: string;
  recorded_at: string;
  change: "created" | "view_updated" | "access_updated";
  view: InvestigationWorkspaceView;
  readers: string[];
  editors: string[];
}

/** Current authorization governs access to the selected historical revision. */
export interface InvestigationTeamWorkspace {
  workspace_id: string;
  owner: string;
  scope: ScopeSelection;
  latest_revision: number;
  revision: InvestigationWorkspaceRevision;
  current_access: { readers: string[]; editors: string[] };
  can_edit: boolean;
  can_share: boolean;
  history: Array<Pick<InvestigationWorkspaceRevision, "revision" | "actor" | "recorded_at" | "change">>;
}

const base = "/investigation-workspaces";

/** Persist navigation through authorized create-only and revision-conditional operations. */
export const investigationWorkspacesApi = {
  /** Create one private workspace at a browser-known identity, without evidence acquisition. */
  create: (workspaceId: string, view: InvestigationWorkspaceView, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<InvestigationTeamWorkspace>(base, {
      method: "POST", body: { workspace_id: workspaceId, view }, query: scopeToSearchParams(scope), signal,
    }),
  /** Reauthorize current membership and scope before opening any selected revision. */
  read: (workspaceId: string, scope: ScopeSelection, revision?: number, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    if (revision !== undefined) query.set("revision", String(revision));
    return apiRequest<InvestigationTeamWorkspace>(`${base}/${encodeURIComponent(workspaceId)}`, { query, signal });
  },
  /** Append current navigation only against the reviewed latest revision. */
  replace: (workspaceId: string, expectedRevision: number, view: InvestigationWorkspaceView, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<InvestigationTeamWorkspace>(`${base}/${encodeURIComponent(workspaceId)}`, {
      method: "PUT", body: { expected_revision: expectedRevision, view }, query: scopeToSearchParams(scope), signal,
    }),
  /** Owner-only membership change; platform read grants are still required independently. */
  share: (workspaceId: string, expectedRevision: number, readers: string[], editors: string[], scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<InvestigationTeamWorkspace>(`${base}/${encodeURIComponent(workspaceId)}/access`, {
      method: "PUT", body: { expected_revision: expectedRevision, readers, editors }, query: scopeToSearchParams(scope), signal,
    }),
};

/** Link a selected navigation revision and its exact stored scope, never a bearer grant. */
export function investigationWorkspaceHref(workspace: InvestigationTeamWorkspace): string {
  const query = scopeToSearchParams(workspace.scope);
  const { view, revision } = workspace.revision;
  query.set("type", view.entry_type);
  query.set("value", view.subject);
  query.set("mode", view.mode);
  query.set("workspace_id", workspace.workspace_id);
  query.set("workspace_revision", String(revision));
  return `/investigate?${query}`;
}
