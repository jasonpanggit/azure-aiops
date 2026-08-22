"use client";

import { Body1, Card, CardHeader, Spinner, Text, tokens } from "@fluentui/react-components";
import { ApiError } from "@/lib/types";

/**
 * Standard tile shell for dashboard/detail cards: title, loading spinner,
 * error/not-implemented state, or content. Used everywhere a card renders
 * data sourced from the Operations API so "not built yet" (501), "upstream
 * down" (502), and "no data" are visually distinct — never silently blank.
 */
export function DataCard({
  title,
  loading,
  error,
  children,
}: {
  title: string;
  loading: boolean;
  error: Error | null;
  children: React.ReactNode;
}) {
  return (
    <Card style={{ minWidth: 220, minHeight: 120 }}>
      <CardHeader header={<Text weight="semibold">{title}</Text>} />
      {loading && <Spinner size="tiny" label="Loading..." />}
      {!loading && error && <ErrorState error={error} />}
      {!loading && !error && children}
    </Card>
  );
}

export function ErrorState({ error }: { error: Error }) {
  if (error instanceof ApiError && error.isNotImplemented) {
    const roadmap = (error.details?.roadmap as string) ?? "a future prompt";
    return (
      <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
        Not yet available — planned for {roadmap}.
      </Body1>
    );
  }
  if (error instanceof ApiError && error.code === "upstream_unavailable") {
    return <Body1 style={{ color: tokens.colorPaletteRedForeground1 }}>Upstream data source unavailable.</Body1>;
  }
  return (
    <Body1 style={{ color: tokens.colorPaletteRedForeground1 }}>{error.message || "Failed to load."}</Body1>
  );
}
