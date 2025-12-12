// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Application Configuration
 * Centralized configuration constants for the application.
 */

// Get API URL from environment variable (set at build time)
// In production: /api prefix for nginx proxy
// In development: defaults to localhost:8000
const getApiBaseUrl = (): string => {
  // Create React App uses process.env.REACT_APP_*
  const envUrl = process.env.REACT_APP_API_URL;
  
  // If explicitly set, use it
  if (envUrl) return envUrl;
  
  // In production (served by nginx), use /api prefix
  if (process.env.NODE_ENV === "production") {
    return "/api";  // nginx proxies /api/* to backend
  }
  
  // Fallback for development
  return "http://localhost:8000";
};

export const APP_CONFIG = {
  API_BASE_URL: getApiBaseUrl(),
  API_TIMEOUT: 120000,
  API_RETRY_ATTEMPTS: 3,
  API_RETRY_DELAY: 1000,
  MAX_MESSAGE_LENGTH: 10000,
  STREAMING_ENABLED: true,
  AUTO_SCROLL_DELAY: 100,
  SIDEBAR_WIDTH: 280,
  SIDEBAR_COLLAPSED_WIDTH: 60,
  MESSAGE_ANIMATION_DURATION: 200,
  JOB_STATUS_POLL_INTERVAL: 2000,
  CONVERSATION_REFRESH_INTERVAL: 30000,
  STORAGE_KEYS: {
    SELECTED_WORKSPACE: "sap-qa-selected-workspace",
    SIDEBAR_COLLAPSED: "sap-qa-sidebar-collapsed",
    LAST_CONVERSATION_ID: "sap-qa-last-conversation",
  },
} as const;

export const ROUTES = {
  HOME: "/",
  CHAT: "/chat",
  CHAT_WITH_ID: "/chat/:conversationId",
} as const;
