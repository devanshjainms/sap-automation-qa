// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { Text, Button } from "@fluentui/react-components";
import { strings } from "../lib/strings";
import { useAuth } from "../providers/AuthProvider";

/**
 * Landing page shown when the user is not authenticated.
 */
export function LandingPage() {
  const { loginRedirect, isLoading } = useAuth();

  return (
    <div style={{ textAlign: "center", padding: "6rem 1rem" }}>
      <Text as="h1" size={900} weight="bold" block>
        {strings.app.name}
      </Text>
      <Text size={400} block style={{ marginTop: "1rem", maxWidth: 480, margin: "1rem auto" }}>
        Orchestrate and validate SAP deployments on Microsoft Azure with
        automated HA functional tests, configuration checks, and AI-powered
        diagnostics.
      </Text>
      <Button
        appearance="primary"
        size="large"
        style={{ marginTop: "2rem" }}
        onClick={loginRedirect}
        disabled={isLoading}
      >
        {isLoading ? strings.auth.signingIn : strings.auth.signIn}
      </Button>
    </div>
  );
}
