"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { KeyboardEvent, ReactNode } from "react";
import { useEffect, useId, useRef, useState } from "react";
import { healthApi, type HealthResponse } from "../lib/services";
import { AccountMenu } from "./AccountMenu";
import { ScopeSelector } from "./ScopeSelector";
import { RouteScopeBoundary } from "./RouteScopeBoundary";

const PRIMARY_NAV = [
  { href: "/", label: "Home", short: "H" },
  { href: "/investigate", label: "Investigate", short: "I" },
  { href: "/agents", label: "Agents", short: "AG" },
  { href: "/situations", label: "Situations", short: "S" },
  { href: "/services", label: "Services", short: "SV" },
  { href: "/network", label: "Topology", short: "T" },
  { href: "/twin", label: "Twin", short: "TW" },
  { href: "/compliance", label: "Compliance", short: "C" },
  { href: "/exposure", label: "Exposure", short: "E" },
  { href: "/inventory", label: "Inventory", short: "IN" },
  { href: "/changes", label: "Changes", short: "CH" },
  { href: "/remediation", label: "Remediation", short: "R" },
  { href: "/finops", label: "FinOps", short: "F" },
  { href: "/identity", label: "Identity", short: "ID" },
  { href: "/resource-health", label: "Health", short: "RH" },
] as const;

const WORKBENCH_NAV = [
  { href: "/copilot", label: "Copilot", short: "AI" },
  { href: "/governance", label: "Governance", short: "G" },
  { href: "/connections", label: "Data & integrations", short: "D" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function NavigationLink({
  href,
  label,
  short,
  pathname,
  onNavigate,
}: {
  href: string;
  label: string;
  short: string;
  pathname: string;
  onNavigate: () => void;
}) {
  const active = isActive(pathname, href);
  return (
    <Link
      href={href}
      className={`shell-nav-link${active ? " shell-nav-link-active" : ""}`}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
    >
      <span className="shell-nav-icon" aria-hidden="true">
        {short}
      </span>
      <span>{label}</span>
    </Link>
  );
}

/** Enterprise workbench shell with persistent operational context and task-oriented navigation. */
export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const navigationId = useId();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const [runtimeHealth, setRuntimeHealth] = useState<HealthResponse | null>(null);

  const dismissNavigation = () => {
    setOpen(false);
    menuButtonRef.current?.focus();
  };

  const handleNavigationKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (!open || event.key !== "Escape" || event.defaultPrevented) return;
    if (!menuButtonRef.current || window.getComputedStyle(menuButtonRef.current).display === "none") return;
    event.preventDefault();
    event.stopPropagation();
    dismissNavigation();
  };

  useEffect(() => {
    let active = true;
    const refresh = () => {
      void healthApi
        .health()
        .then((health) => {
          if (active) setRuntimeHealth(health);
        })
        .catch(() => {
          if (active) setRuntimeHealth(null);
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const healthState = runtimeHealth?.readiness ?? "degraded";
  const healthLabel =
    runtimeHealth === null
      ? "Runtime unavailable"
      : healthState === "ready"
        ? "Knowledge current"
        : healthState === "stale"
          ? "Knowledge stale"
          : healthState === "partial"
            ? "Providers partial"
            : "Runtime degraded";

  return (
    <div className="workbench-shell">
      <header className="shell-topbar">
        <button
          ref={menuButtonRef}
          type="button"
          className="shell-menu-button"
          aria-label="Toggle navigation"
          aria-expanded={open}
          aria-controls={navigationId}
          onKeyDown={handleNavigationKeyDown}
          onClick={() => setOpen((value) => !value)}
        >
          <span />
          <span />
          <span />
        </button>
        <Link href="/" className="shell-brand" onClick={() => setOpen(false)}>
          <span className="shell-brand-mark" aria-hidden="true">
            A
          </span>
          <span className="shell-brand-copy">
            <strong>AI Operations</strong>
            <span>Workbench</span>
          </span>
        </Link>
        <div className="shell-context">
          <span className="shell-context-label">Operating context</span>
          <ScopeSelector />
        </div>
        <div className="shell-status" title="Read-only recommendations require operator approval">
          <span className="shell-status-dot" />
          Advisory mode
        </div>
        <AccountMenu />
      </header>

      <aside id={navigationId} className={`shell-sidebar${open ? " shell-sidebar-open" : ""}`} aria-label="Primary navigation" onKeyDown={handleNavigationKeyDown}>
        <nav>
          <div className="shell-nav-label">Operate</div>
          {PRIMARY_NAV.map((item) => (
            <NavigationLink
              key={item.href}
              {...item}
              pathname={pathname}
              onNavigate={() => setOpen(false)}
            />
          ))}
          <div className="shell-nav-divider" />
          <div className="shell-nav-label">Workbench</div>
          {WORKBENCH_NAV.map((item) => (
            <NavigationLink
              key={item.href}
              {...item}
              pathname={pathname}
              onNavigate={() => setOpen(false)}
            />
          ))}
        </nav>
        <div className="shell-sidebar-footer">
          <div
            className={`shell-health-row shell-health-${healthState}`}
            title={runtimeHealth?.degraded_reason || runtimeHealth?.ontology_version || ""}
          >
            <span className="shell-status-dot" />
            {healthLabel}
          </div>
          <span>Evidence-backed operational intelligence</span>
        </div>
      </aside>

      {open && <button type="button" className="shell-backdrop" aria-label="Close navigation" onClick={dismissNavigation} onKeyDown={handleNavigationKeyDown} />}
      <main className="shell-main"><RouteScopeBoundary>{children}</RouteScopeBoundary></main>
    </div>
  );
}
