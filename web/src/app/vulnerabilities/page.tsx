import { redirect } from "next/navigation";
import { legacyExposureBookmark } from "@/lib/exposure-query-state";

/**
 * Preserves the legacy vulnerability route while consolidating the product
 * under Exposure.
 *
 * Copilot disposition (Plan 11-16): `redirect`. This alias hosts no Copilot
 * page adapter and never renders the shared contextual launcher -- it resolves
 * only to the canonical Exposure product, so the reviewed 28-route disposition
 * gate keeps it from silently duplicating an integrated adapter (D-03).
 */
export default function VulnerabilitiesPage({
  searchParams = {},
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const bookmark = legacyExposureBookmark(searchParams);
  console.info(JSON.stringify({
    event: "legacy_exposure_redirect",
    count: 1,
    translated_parameter_names: bookmark.translatedNames,
    discarded_key_count: bookmark.discardedKeyCount,
  }));
  const suffix = bookmark.query.toString();
  redirect(`/exposure/patch-priorities${suffix ? `?${suffix}` : ""}`);
}
