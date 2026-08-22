"use client";

import type { Action, Principal } from "@/lib/permissions";
import { canPerform } from "@/lib/permissions";

interface RequirePermissionProps {
  principal: Principal | null;
  action: Action;
  children: React.ReactNode;
  /** Rendered instead of children when the action is not permitted. Defaults to nothing. */
  fallback?: React.ReactNode;
}

/**
 * Gates a UI affordance (button, panel, route) by RBAC action. This is a
 * convenience layer only — see lib/permissions.ts for why the API remains
 * the authority on every mutating call.
 */
export function RequirePermission({ principal, action, children, fallback = null }: RequirePermissionProps) {
  if (!canPerform(principal, action)) return <>{fallback}</>;
  return <>{children}</>;
}
