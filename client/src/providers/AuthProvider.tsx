// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * React context provider for MSAL authentication.
 *
 * Wraps the app with ``MsalProvider`` from ``@azure/msal-react`` and
 * exposes auth state (user, loading, error) via a custom hook.
 * Includes ``AuthGuard`` to block rendering until the user is signed in,
 * showing a branded landing page for unauthenticated visitors.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { MsalProvider, useMsal, useIsAuthenticated } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import type { AccountInfo, PublicClientApplication } from "@azure/msal-browser";
import {
  getMsalInstance,
  fetchAuthConfig,
  type AuthConfig,
} from "../lib/auth";
import { strings } from "../lib/strings";
import { useStyles } from "../styles/authGuard.styles";
import { LandingPage } from "../pages/LandingPage";

interface AuthContextValue {
  ready: boolean;
  error: string | null;
  config: AuthConfig | null;
}

const AuthContext = createContext<AuthContextValue>({
  ready: false,
  error: null,
  config: null,
});

/**
 * Inner provider that lives inside MsalProvider and exposes
 * convenience auth state to descendants.
 */
function AuthStateProvider({
  children,
  config,
}: {
  children: ReactNode;
  config: AuthConfig;
}) {
  return (
    <AuthContext.Provider value={{ ready: true, error: null, config }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Top-level auth provider. Fetches config, initializes MSAL,
 * then wraps children with ``MsalProvider`` + ``AuthStateProvider``.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [msalInstance, setMsalInstance] =
    useState<PublicClientApplication | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await fetchAuthConfig();
        const instance = await getMsalInstance();
        if (!cancelled) {
          setConfig(cfg);
          setMsalInstance(instance);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : strings.shared.error,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <AuthContext.Provider value={{ ready: false, error, config: null }}>
        {children}
      </AuthContext.Provider>
    );
  }

  if (!msalInstance || !config) {
    return (
      <AuthContext.Provider
        value={{ ready: false, error: null, config: null }}
      >
        {children}
      </AuthContext.Provider>
    );
  }

  return (
    <MsalProvider instance={msalInstance}>
      <AuthStateProvider config={config}>{children}</AuthStateProvider>
    </MsalProvider>
  );
}

/** Access the auth context (ready, error, config). */
export function useAuthContext(): AuthContextValue {
  return useContext(AuthContext);
}

/** Convenience hook combining MSAL state with our auth context. */
export function useAuth() {
  const { ready, error, config } = useAuthContext();
  const { instance, inProgress, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const account: AccountInfo | null = accounts[0] ?? null;

  const loginRedirect = useCallback(async () => {
    if (!config) return;
    await instance.loginRedirect({
      scopes: config.scopes,
      redirectUri: window.location.origin,
    });
  }, [instance, config]);

  const logoutRedirect = useCallback(async () => {
    if (!account) return;
    await instance.logoutRedirect({
      account,
      postLogoutRedirectUri: window.location.origin,
    });
  }, [instance, account]);

  return {
    ready,
    error,
    isAuthenticated,
    isLoading: !ready || inProgress !== InteractionStatus.None,
    account,
    loginRedirect,
    logoutRedirect,
  };
}

/**
 * Auth guard that blocks rendering until the user is authenticated.
 * Shows a branded landing page with sign-in button instead of
 * auto-redirecting to Azure AD.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { ready, error } = useAuthContext();
  const { inProgress, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const classes = useStyles();

  if (!ready && !error) {
    return (
      <div className={classes.overlay}>
        <p>{strings.auth.initializingAuth}</p>
      </div>
    );
  }

  if (inProgress !== InteractionStatus.None) {
    return (
      <div className={classes.overlay}>
        <p>{strings.auth.signingIn}</p>
      </div>
    );
  }

  if (error || !isAuthenticated || accounts.length === 0) {
    return <LandingPage />;
  }

  return <>{children}</>;
}
