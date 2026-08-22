import { redirect } from "next/navigation";

/** Preserves the legacy vulnerability route while consolidating the product under Exposure. */
export default function VulnerabilitiesPage() {
  redirect("/exposure");
}
