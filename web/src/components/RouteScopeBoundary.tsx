"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useMemo, type ReactNode } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { ThreadContinuityProvider } from "@/lib/copilot/thread-context";
import { SCOPE_DIMENSIONS, SCOPE_DIMENSION_LABELS, ScopeBookmarkError, scopedBookmark, scopeToSearchParams } from "@/lib/scope";
import { PageScopeProvider, useScope } from "@/lib/scope-context";

/** Restore narrowing URL scope before page providers or contextual Copilot can mount. */
export function RouteScopeBoundary({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="page-container"><StatePanel title="Restoring page scope" message="Page data is withheld until its bookmarked scope is checked." tone="loading" /></div>}><ScopedRoute>{children}</ScopedRoute></Suspense>;
}

function ScopedRoute({ children }: { children: ReactNode }) {
  const { scope } = useScope();
  const params = useSearchParams();
  const pathname = usePathname();
  const scopeParams = new URLSearchParams();
  for (const dimension of SCOPE_DIMENSIONS) {
    for (const value of params.getAll(dimension)) scopeParams.append(dimension, value);
  }
  const scopeQuery = scopeParams.toString();
  const result = useMemo(() => {
    try {
      return { selected: scopedBookmark(new URLSearchParams(scopeQuery), scope), error: null };
    } catch (error) {
      if (!(error instanceof ScopeBookmarkError)) throw error;
      return { selected: null, error: error.message };
    }
  }, [scope, scopeQuery]);
  const recovery = new URLSearchParams(params.toString());
  for (const dimension of SCOPE_DIMENSIONS) recovery.delete(dimension);
  scopeToSearchParams(scope).forEach((value, key) => recovery.append(key, value));
  const recoveryHref = `${pathname}${recovery.size ? `?${recovery}` : ""}`;

  let content: ReactNode;
  if (!result.selected) {
    content = <div className="page-container"><StatePanel title="Page bookmark scope unavailable" message={result.error} tone="error" action={<Link className="button button-secondary" href={recoveryHref}>Use current operating context</Link>} /></div>;
  } else {
    const selected = result.selected;
    content = <>
      {scopeQuery && <aside className="page-scope-notice" aria-label="Bookmarked page scope">
        <p><strong>Page scope: </strong>{SCOPE_DIMENSIONS.flatMap(dimension => selected[dimension]?.length ? [`${SCOPE_DIMENSION_LABELS[dimension]}: ${selected[dimension]?.join(", ")}`] : []).join("; ")}</p>
        <p>This page bookmark leaves the global operating context unchanged. The API reauthorizes each read. <Link href={recoveryHref}>Use current operating context</Link></p>
      </aside>}
      <Fragment key={JSON.stringify(selected)}>{children}</Fragment>
    </>;
  }
  return <PageScopeProvider scope={result.selected ?? scope}>
    <ThreadContinuityProvider>{content}</ThreadContinuityProvider>
  </PageScopeProvider>;
}
