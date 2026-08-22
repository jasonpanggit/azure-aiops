"use client";

import { Button, Text } from "@fluentui/react-components";
import { Component, type ErrorInfo, type ReactNode } from "react";

const wrapStyle = {
  display: "flex",
  flexDirection: "column" as const,
  alignItems: "center",
  justifyContent: "center",
  minHeight: "40vh",
  gap: "12px",
  padding: "24px",
};

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Top-level React error boundary. Catches render-time exceptions anywhere in
 * the workbench and shows a recoverable fallback instead of a blank screen.
 * API/network errors are handled separately per-view (see lib/api-client.ts's
 * ApiError) — this boundary is the last line of defense for unexpected bugs.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (typeof window !== "undefined" && window.appInsights) {
      window.appInsights.trackException({ exception: error, properties: { componentStack: info.componentStack ?? "" } });
    } else if (process.env.NODE_ENV !== "production") {
      console.error("[ErrorBoundary]", error, info);
    }
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div style={wrapStyle}>
          <Text size={500} weight="semibold">
            Something went wrong
          </Text>
          <Text>{this.state.error.message}</Text>
          <Button appearance="primary" onClick={this.reset}>
            Try again
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
