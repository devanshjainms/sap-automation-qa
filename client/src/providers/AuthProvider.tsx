// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * React context provider for MSAL authentication.
 *
 * Wraps the app with ``MsalProvider`` from ``@azure/msal-react`` and
 * exposes auth state (user, loading, error) via a custom hook.
 * Includes ``AuthGuard`` to block rendering until the user is signed in.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
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
import { useStyles } from "../styles/authGuard.styles";

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
            err instanceof Error ? err.message : "Auth initialization failed",
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

  const loginPopup = useCallback(async () => {
    if (!config) return;
    await instance.loginPopup({ scopes: config.scopes });
  }, [instance, config]);

  const logoutPopup = useCallback(async () => {
    if (!account) return;
    await instance.logoutPopup({ account });
  }, [instance, account]);

  return {
    ready,
    error,
    isAuthenticated,
    isLoading: !ready || inProgress !== InteractionStatus.None,
    account,
    loginPopup,
    logoutPopup,
  };
}

/**
 * Auth guard that blocks rendering until the user is authenticated.
 * Automatically triggers a redirect login when MSAL is ready but
 * no user session exists.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { ready, error, config } = useAuthContext();
  const { instance, inProgress, accounts } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const loginAttempted = useRef(false);
  const classes = useStyles();

  useEffect(() => {
    if (
      ready &&
      config &&
      !isAuthenticated &&
      inProgress === InteractionStatus.None &&
      !loginAttempted.current
    ) {
      loginAttempted.current = true;
      instance.loginRedirect({ scopes: config.scopes }).catch(() => {
        loginAttempted.current = false;
      });
    }
  }, [ready, config, isAuthenticated, inProgress, instance]);

  if (!ready && !error) {
    return (
      <div className={classes.overlay}>
        <p>Initializing authentication…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={classes.overlay}>
        <h2>Authentication Error</h2>
        <p>{error}</p>
        <button
          className={classes.retryButton}
          onClick={() => window.location.reload()}
        >
          Retry
        </button>
      </div>
    );
  }

  if (inProgress !== InteractionStatus.None) {
    return (
      <div className={classes.overlay}>
        <p>Signing in…</p>
      </div>
    );
  }

  if (!isAuthenticated || accounts.length === 0) {
    return (
      <div className={classes.overlay}>
        <h2>Sign in required</h2>
        <p>Redirecting to Azure AD…</p>
      </div>
    );
  }

  return <>{children}</>;
}
