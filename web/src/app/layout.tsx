import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import { Providers } from "@/components/Providers";
import { ScopeProvider } from "@/lib/scope-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Azure AI Operations Workbench",
  description: "Service-aware operational intelligence across Azure environments.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <ScopeProvider>
            <AppShell>{children}</AppShell>
          </ScopeProvider>
        </Providers>
      </body>
    </html>
  );
}
