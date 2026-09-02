"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const EXPOSURE_TABS = [
  { href: "/exposure", label: "Overview", exact: true },
  { href: "/exposure/defender-posture", label: "Defender posture", exact: false },
  { href: "/exposure/patch-priorities", label: "Patch priorities", exact: false },
] as const;

/** Layout wrapper for exposure routes. Renders shared sub-navigation across the split exposure pages. */
export default function ExposureLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <div role="tablist" aria-label="Exposure views" className="tab-list">
        {EXPOSURE_TABS.map((item) => {
          const isActive = item.exact ? pathname === item.href : pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              role="tab"
              aria-selected={isActive}
              tabIndex={isActive ? 0 : -1}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
      {children}
    </>
  );
}
