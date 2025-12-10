// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Application Strings
 * Centralized string constants for UI text and messages.
 */

export const APP_STRINGS = {
  APP_NAME: "SAP QA Copilot",
  APP_TITLE: "SAP QA Copilot",
  APP_SUBTITLE: "SAP Testing Automation Assistant",
  CHAT_PLACEHOLDER:
    "Ask about SAP workspaces, run HA tests, or get documentation help...",
  CHAT_SEND_BUTTON: "Send",
  CHAT_STOP_BUTTON: "Stop",
  CHAT_EMPTY_STATE_TITLE: "How can I help you today?",
  CHAT_EMPTY_STATE_SUBTITLE:
    "Ask me about SAP workspaces, HA testing, or configuration checks.",
  CHAT_THINKING: "Thinking...",
  CHAT_ERROR: "Something went wrong. Please try again.",
  SIDEBAR_TITLE: "Conversations",
  SIDEBAR_NEW_CHAT: "New chat",
  SIDEBAR_NO_CONVERSATIONS: "No conversations yet",
  SIDEBAR_DELETE_CONFIRM: "Delete this conversation?",
  SIDEBAR_RENAME_TITLE: "Rename conversation",
  WORKSPACE_SELECTOR_LABEL: "Workspace",
  WORKSPACE_SELECTOR_PLACEHOLDER: "Select workspace as context",
  WORKSPACE_SELECTOR_NO_SELECTION: "No workspace selected",
  WORKSPACE_SELECTOR_LOADING: "Loading workspaces...",
  WORKSPACE_SELECTOR_ERROR: "Failed to load workspaces",
  TRACE_TITLE: "Reasoning Steps",
  TRACE_EXPAND: "Show reasoning",
  TRACE_COLLAPSE: "Hide reasoning",
  TRACE_STEP_ROUTING: "Routing",
  TRACE_STEP_TOOL_CALL: "Tool Call",
  TRACE_STEP_INFERENCE: "Inference",
  TRACE_STEP_DECISION: "Decision",
  TEST_STATUS_PENDING: "Pending",
  TEST_STATUS_RUNNING: "Running",
  TEST_STATUS_COMPLETED: "Completed",
  TEST_STATUS_FAILED: "Failed",
  TEST_PANEL_TITLE: "Test Execution",
  TEST_PANEL_EMPTY: "No active test executions",
  ACTION_COPY: "Copy",
  ACTION_COPIED: "Copied!",
  ACTION_RETRY: "Retry",
  ACTION_CANCEL: "Cancel",
  ACTION_SAVE: "Save",
  ACTION_DELETE: "Delete",
  ACTION_RENAME: "Rename",
  ERROR_NETWORK: "Network error. Please check your connection.",
  ERROR_SERVER: "Server error. Please try again later.",
  ERROR_TIMEOUT: "Request timed out. Please try again.",
  ERROR_UNKNOWN: "An unexpected error occurred.",
  SUGGESTION_WORKSPACES: "What workspaces are available?",
  SUGGESTION_HA_TESTS: "What HA tests can I run?",
  SUGGESTION_CONFIG_CHECK: "Run configuration checks for X00",
  SUGGESTION_CAPABILITIES: "Show capabilities for DEV-WEEU-SAP01-X00",
} as const;

export const LABELS = {
  CHAT: "Chat",
  TEST_EXECUTION: "Test Execution",
  WORKSPACES: "Workspaces",
  SETTINGS: "Settings",
} as const;

export type AppStringKey = keyof typeof APP_STRINGS;
export type LabelKey = keyof typeof LABELS;
