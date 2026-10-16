"use client";

import { createContext, useContext, useMemo, useState } from "react";
import { emptyScope, type ScopeSelection } from "@/lib/scope";

interface ScopeContextValue {
  scope: ScopeSelection;
  setScope: (scope: ScopeSelection) => void;
  clearScope: () => void;
}

const ScopeContext = createContext<ScopeContextValue | null>(null);

/**
 * Holds the globally selected scope (business service, application,
 * environment, subscription, owner, support team, region, criticality)
 * shared across every view — dashboard, search, connections, graph.
 */
export function ScopeProvider({
  children,
  initialScope,
}: {
  children: React.ReactNode;
  initialScope?: ScopeSelection;
}) {
  const [scope, setScope] = useState<ScopeSelection>(initialScope ?? emptyScope());

  const value = useMemo<ScopeContextValue>(
    () => ({
      scope,
      setScope,
      clearScope: () => setScope(emptyScope()),
    }),
    [scope]
  );

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useScope(): ScopeContextValue {
  const ctx = useContext(ScopeContext);
  if (!ctx) throw new Error("useScope must be used within a ScopeProvider");
  return ctx;
}

/** Apply an effective page scope without replacing the user's global selector or its controls. */
export function PageScopeProvider({ scope, children }: { scope: ScopeSelection; children: React.ReactNode }) {
  const parent = useScope();
  const value = useMemo(() => ({ ...parent, scope }), [parent, scope]);
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}
