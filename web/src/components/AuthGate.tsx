"use client";

import { AuthenticatedTemplate, UnauthenticatedTemplate, useIsAuthenticated, useMsal } from "@azure/msal-react";
import { Button, MessageBar, MessageBarBody, MessageBarTitle, Spinner, Text, tokens } from "@fluentui/react-components";
import { InteractionStatus } from "@azure/msal-browser";
import { apiLoginRequest, isMsalConfigured } from "@/lib/auth";

/**
 * Gates the workbench behind sign-in when an Entra app registration is
 * configured. Falls back to a dev-token banner + pass-through when it is
 * not, so local development works without a tenant (see lib/auth.ts).
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!isMsalConfigured) {
    return (
      <div>
        <MessageBar intent="warning">
          <MessageBarBody>
            <MessageBarTitle>Development mode</MessageBarTitle>
            No Entra ID app registration configured (NEXT_PUBLIC_ENTRA_CLIENT_ID is unset). Using
            AIOPS_DEV_TOKEN for API calls. Do not use this configuration in production.
          </MessageBarBody>
        </MessageBar>
        {children}
      </div>
    );
  }

  return (
    <>
      <AuthenticatedTemplate>{children}</AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <SignInPrompt />
      </UnauthenticatedTemplate>
    </>
  );
}

function SignInPrompt() {
  const { instance, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  if (isAuthenticated) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        gap: tokens.spacingVerticalM,
      }}
    >
      <Text size={600} weight="semibold">
        Azure AI Operations Workbench
      </Text>
      <Text>Sign in with your organizational account to continue.</Text>
      {inProgress !== InteractionStatus.None ? (
        <Spinner label="Signing in..." />
      ) : (
        <Button appearance="primary" onClick={() => instance.loginRedirect(apiLoginRequest)}>
          Sign in
        </Button>
      )}
    </div>
  );
}
