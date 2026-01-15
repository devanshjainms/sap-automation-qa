// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * API Endpoints - Centralized endpoint definitions.
 */
export const API_ENDPOINTS = {
  HEALTH: "/healthz",
  CHAT: "/chat",
  CONVERSATIONS: "/conversations",
  CONVERSATION_BY_ID: (id: string) => `/conversations/${id}`,
  CONVERSATION_MESSAGES: (id: string) => `/conversations/${id}/messages`,
  WORKSPACES: "/workspaces",
  WORKSPACE_BY_ID: (id: string) => `/workspaces/${id}`,
  WORKSPACE_REPORTS: (workspaceId: string) => `/workspaces/${workspaceId}/reports`,
  WORKSPACE_REPORT_FILE: (workspaceId: string, filePath: string) => 
    `/workspaces/${workspaceId}/reports/${filePath}`,
  JOBS: "/jobs",
  JOB_BY_ID: (id: string) => `/jobs/${id}`,
  JOB_STATUS: (id: string) => `/jobs/${id}/status`,
  SCHEDULES: {
    LIST: "/schedules",
    GET: (id: string) => `/schedules/${id}`,
    TOGGLE: (id: string) => `/schedules/${id}/toggle`,
  },
} as const;

export const buildConversationsQuery = (params: {
  limit?: number;
  offset?: number;
  userId?: string;
}): string => {
  const searchParams = new URLSearchParams();
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.offset) searchParams.set("offset", params.offset.toString());
  if (params.userId) searchParams.set("user_id", params.userId);
  return searchParams.toString();
};

export const buildChatQuery = (params: {
  conversationId?: string;
  userId?: string;
}): string => {
  const searchParams = new URLSearchParams();
  if (params.conversationId)
    searchParams.set("conversation_id", params.conversationId);
  if (params.userId) searchParams.set("user_id", params.userId);
  return searchParams.toString();
};
