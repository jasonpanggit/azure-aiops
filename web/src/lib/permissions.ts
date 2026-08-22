/**
 * Client-side mirror of src/api/rbac.py's role model, used only to gate UI
 * affordances (e.g. hide a "Disable connection" button). The API is the
 * authority: every mutating call is re-checked server-side regardless of
 * what the UI shows, per docs/OPERATIONS_API.md's two-enforcement-point rule.
 */

export type Role = "reader" | "operator" | "admin";
export type Action = "read" | "operate" | "write";

const ROLE_ACTIONS: Record<Role, Set<Action>> = {
  reader: new Set<Action>(["read"]),
  operator: new Set<Action>(["read", "operate"]),
  admin: new Set<Action>(["read", "operate", "write"]),
};

export interface Grant {
  role: Role;
  scope?: Partial<Record<"subscription" | "business_service", string[]>>;
}

export interface Principal {
  subject: string;
  grants: Grant[];
}

/** True if any grant held by the principal permits the action, ignoring scope narrowing. */
export function canPerform(principal: Principal | null, action: Action): boolean {
  if (!principal) return false;
  return principal.grants.some((grant) => ROLE_ACTIONS[grant.role]?.has(action));
}

export function highestRole(principal: Principal | null): Role | null {
  if (!principal || principal.grants.length === 0) return null;
  if (principal.grants.some((g) => g.role === "admin")) return "admin";
  if (principal.grants.some((g) => g.role === "operator")) return "operator";
  return "reader";
}
