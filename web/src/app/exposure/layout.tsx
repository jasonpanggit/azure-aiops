"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, type ReactNode } from "react";
import { usePathname, useSearchParams } from "next/navigation";

const EXPOSURE_VIEWS = [
  { href: "/exposure", label: "Overview" },
  { href: "/exposure/defender-posture", label: "Defender exposure" },
  { href: "/exposure/patch-priorities", label: "Patch priorities" },
] as const;

type ExposureView = (typeof EXPOSURE_VIEWS)[number]["href"];

const DETAIL_PARENTS = new Set<ExposureView>([
  "/exposure",
  "/exposure/defender-posture",
  "/exposure/patch-priorities",
]);

function selectedView(pathname: string, origin: string | null): ExposureView {
  if (pathname === "/exposure") return "/exposure";
  if (pathname.startsWith("/exposure/defender-posture")) {
    return "/exposure/defender-posture";
  }
  if (pathname.startsWith("/exposure/patch-priorities")) {
    return "/exposure/patch-priorities";
  }
  if (
    pathname.startsWith("/exposure/cves/") ||
    pathname.startsWith("/exposure/kbs/")
  ) {
    return DETAIL_PARENTS.has(origin as ExposureView)
      ? (origin as ExposureView)
      : "/exposure/patch-priorities";
  }
  return "/exposure/patch-priorities";
}

function ExposureLayoutContent({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const activeView = selectedView(pathname, searchParams.get("origin"));
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const revealCurrentLink = () => {
      const focused = document.activeElement;
      const link = focused instanceof HTMLAnchorElement && nav.contains(focused)
        ? focused
        : nav.querySelector<HTMLAnchorElement>('[aria-current="page"]');
      if (!link) return;
      const bounds = nav.getBoundingClientRect();
      const left = bounds.left + nav.clientLeft;
      const right = left + nav.clientWidth;
      const rect = link.getBoundingClientRect();
      if (rect.left < left) nav.scrollLeft += rect.left - left;
      else if (rect.right > right) nav.scrollLeft += rect.right - right;
    };
    revealCurrentLink();
    window.addEventListener("resize", revealCurrentLink);
    return () => window.removeEventListener("resize", revealCurrentLink);
  }, [activeView]);

  return (
    <>
      <nav ref={navRef} aria-label="Exposure views" className="tab-list exposure-nav">
        {EXPOSURE_VIEWS.map((item) => {
          const isActive = activeView === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="tab-link"
              aria-current={isActive ? "page" : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </>
  );
}

/** Layout wrapper for exposure routes. Renders shared sub-navigation across the split exposure pages. */
export default function ExposureLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="page-container" role="status">
          Loading exposure view…
        </div>
      }
    >
      <ExposureLayoutContent>{children}</ExposureLayoutContent>
    </Suspense>
  );
}
