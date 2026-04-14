// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * MSAL (Azure AD) authentication configuration and helpers.
 *
 * Fetches auth config from the backend `/auth/config` endpoint at runtime
 * so that client IDs and tenant IDs are never baked into the JS bundle.
 */

import {
  PublicClientApplication,
  LogLevel,
} from "@azure/msal-browser";
import type {
  Configuration,
  SilentRequest,
  PopupRequest,
  AccountInfo,
} from "@azure/msal-browser";

export interface AuthConfig {
  tenant_id: string;
  client_id: string;
  authority: string;
  scopes: string[];
}

let _cachedConfig: AuthConfig | null = null;
let _msalInstance: PublicClientApplication | null = null;

/**
 * Fetch auth configuration from the backend.
 * Result is cached for the lifetime of the page.
 */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  if (_cachedConfig) return _cachedConfig;

  const res = await fetch("/auth/config");
  if (!res.ok) {
    throw new Error(`Failed to fetch auth config: ${res.status}`);
  }
  _cachedConfig = (await res.json()) as AuthConfig;
  return _cachedConfig;
}

/**
 * Build the MSAL configuration object from backend-provided config.
 */
function buildMsalConfig(config: AuthConfig): Configuration {
  return {
    auth: {
      clientId: config.client_id,
      authority: config.authority,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: {
      cacheLocation: "sessionStorage",
    },
    system: {
      loggerOptions: {
        logLevel: LogLevel.Warning,
        loggerCallback: (_level, message) => {
          console.debug("[MSAL]", message);
        },
      },
    },
  };
}

/**
 * Initialize and return the singleton MSAL PublicClientApplication.
 * Must be called after fetchAuthConfig.
 */
export async function getMsalInstance(): Promise<PublicClientApplication> {
  if (_msalInstance) return _msalInstance;

  const config = await fetchAuthConfig();
  _msalInstance = new PublicClientApplication(buildMsalConfig(config));
  await _msalInstance.initialize();
  await _msalInstance.handleRedirectPromise();

  return _msalInstance;
}

/**
 * Acquire an access token silently, falling back to popup on failure.
 *
 * @returns Bearer token string, or null if not authenticated.
 */
export async function acquireToken(): Promise<string | null> {
  const instance = await getMsalInstance();
  const config = await fetchAuthConfig();
  const accounts = instance.getAllAccounts();

  if (accounts.length === 0) return null;

  const silentRequest: SilentRequest = {
    scopes: config.scopes,
    account: accounts[0],
  };

  try {
    const response = await instance.acquireTokenSilent(silentRequest);
    return response.accessToken;
  } catch {
    try {
      const popupRequest: PopupRequest = { scopes: config.scopes };
      const response = await instance.acquireTokenPopup(popupRequest);
      return response.accessToken;
    } catch {
      return null;
    }
  }
}

/**
 * Get the currently active account, if any.
 */
export async function getActiveAccount(): Promise<AccountInfo | null> {
  const instance = await getMsalInstance();
  const accounts = instance.getAllAccounts();
  return accounts[0] ?? null;
}

/**
 * Trigger interactive login via popup.
 */
export async function login(): Promise<void> {
  const instance = await getMsalInstance();
  const config = await fetchAuthConfig();
  await instance.loginPopup({ scopes: config.scopes });
}

/**
 * Log out the current user.
 */
export async function logout(): Promise<void> {
  const instance = await getMsalInstance();
  const accounts = instance.getAllAccounts();
  if (accounts.length > 0) {
    await instance.logoutPopup({ account: accounts[0] });
  }
}
