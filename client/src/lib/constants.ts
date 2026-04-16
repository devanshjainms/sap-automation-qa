// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Application constants.
 *
 * Shared numeric limits, storage keys, status colours, navigation
 * structure, and AG-UI agent identifiers.
 */

import React from "react";
import {
  Home24Regular,
  TaskListSquareLtr24Regular,
  CalendarClock24Regular,
  BuildingMultiple24Regular,
  HeartPulse24Regular,
} from "@fluentui/react-icons";

/** AG-UI agent identifier. */
export const AGENT_ID = "sap-agent";

/** localStorage key map. */
export const STORAGE_KEYS = {
  theme: "staf-theme",
};

/** Characters shown when displaying truncated job IDs. */
export const JOB_ID_DISPLAY_LENGTH = 8;

/** Number of tail lines to fetch for job logs. */
export const JOB_LOG_TAIL_LINES = 500;

/** Number of recent jobs shown on the dashboard. */
export const RECENT_JOBS_COUNT = 10;

/** How many chat conversations to show before "Load more". */
export const INITIAL_VISIBLE_CHATS = 10;

/** Health-check service keys (order matches UI). */
export const SERVICE_KEYS = [
  "api",
  "scheduler",
  "mcp",
  "llm",
] as const;

/** Human-readable labels for each service key. */
export const SERVICE_LABELS: Record<string, string> = {
  api: "Core API",
  scheduler: "Scheduler",
  mcp: "MCP Server",
  llm: "LLM Endpoint",
};

/** Valid Badge color values from FluentUI. */
type BadgeColor =
  | "success"
  | "brand"
  | "informative"
  | "danger"
  | "warning"
  | "subtle"
  | "important"
  | "severe";

/** Badge colour mapping for job/schedule statuses. */
export const STATUS_BADGE_COLORS: Record<string, BadgeColor> = {
  completed: "success",
  running: "brand",
  pending: "informative",
  queued: "informative",
  failed: "danger",
  cancelled: "warning",
  active: "success",
  paused: "warning",
};

/** Primary sidebar navigation items. */
export const NAV_ITEMS: Array<{
  to: string;
  icon: React.ReactNode;
  labelKey: keyof typeof import("./strings").strings.nav;
  end?: boolean;
}> = [
  { to: "/", icon: React.createElement(Home24Regular), labelKey: "jobs", end: true },
  { to: "/jobs", icon: React.createElement(TaskListSquareLtr24Regular), labelKey: "jobs" },
  { to: "/schedules", icon: React.createElement(CalendarClock24Regular), labelKey: "schedules" },
  { to: "/workspaces", icon: React.createElement(BuildingMultiple24Regular), labelKey: "workspaces" },
  { to: "/status", icon: React.createElement(HeartPulse24Regular), labelKey: "serviceStatus" },
];

/** Build the Agent DevUI URL from the current origin. */
export function getDevUiUrl(): string {
  const port = "8080";
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}
