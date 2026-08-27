import type { ReactNode } from "react";

export interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
  metadata?: ReactNode;
}

/** Consistent title block for operational workbench pages. */
export function PageHeader({ eyebrow, title, description, actions, metadata }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        <div className="page-header-signal">
          <span className="page-header-signal-dot" />
          <span>Evidence-backed command view</span>
        </div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
        {metadata && <div className="page-header-metadata">{metadata}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
