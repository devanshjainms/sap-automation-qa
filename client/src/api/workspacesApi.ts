// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspaces API Service - SAP workspace discovery and management.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import { Workspace, Job } from "../types";

export interface WorkspaceListResponse {
  workspaces: Workspace[];
  count: number;
}

export interface WorkspaceDetailResponse {
  workspace: Workspace;
  scs_hosts?: string[];
  db_hosts?: string[];
}

export interface ListWorkspacesParams {
  sid?: string;
  env?: string;
}

export interface TriggerTestExecutionRequest {
  test_group: "HA_DB_HANA" | "HA_SCS" | "HA_OFFLINE" | "CONFIG_CHECKS";
  test_cases?: string[];
  extra_vars?: Record<string, any>;
  offline?: boolean;
}

export interface TriggerTestExecutionResponse {
  job_id: string;
  workspace_id: string;
  test_group: string;
  status: string;
  test_ids: string[];
}

export const workspacesApi = {
  list: async (
    params?: ListWorkspacesParams,
  ): Promise<WorkspaceListResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.sid) searchParams.set("sid", params.sid);
    if (params?.env) searchParams.set("env", params.env);

    const query = searchParams.toString();
    const url = query
      ? `${API_ENDPOINTS.WORKSPACES}?${query}`
      : API_ENDPOINTS.WORKSPACES;

    const response = await apiClient.get<WorkspaceListResponse>(url);
    return response.data;
  },

  getById: async (workspaceId: string): Promise<WorkspaceDetailResponse> => {
    const response = await apiClient.get<WorkspaceDetailResponse>(
      API_ENDPOINTS.WORKSPACE_BY_ID(workspaceId),
    );
    return response.data;
  },

  create: async (workspaceName: string): Promise<Workspace> => {
    const response = await apiClient.post<Workspace>(API_ENDPOINTS.WORKSPACES, {
      workspace_id: workspaceName,
      clone_from: "DEV-WEEU-SAP01-X00",
    });
    return response.data;
  },

  delete: async (workspaceId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.WORKSPACE_BY_ID(workspaceId));
  },

  getFileContent: async (
    workspaceId: string,
    fileName: string,
  ): Promise<string> => {
    const response = await apiClient.get<{ content: string }>(
      `${API_ENDPOINTS.WORKSPACE_BY_ID(workspaceId)}/files/${fileName}`,
    );
    return response.data.content;
  },

  updateFileContent: async (
    workspaceId: string,
    fileName: string,
    content: string,
  ): Promise<void> => {
    await apiClient.put(
      `${API_ENDPOINTS.WORKSPACE_BY_ID(workspaceId)}/files/${fileName}`,
      { content },
    );
  },

  triggerExecution: async (
    workspaceId: string,
    request: TriggerTestExecutionRequest,
  ): Promise<TriggerTestExecutionResponse> => {
    const response = await apiClient.post<TriggerTestExecutionResponse>(
      API_ENDPOINTS.WORKSPACE_EXECUTE(workspaceId),
      request,
    );
    return response.data;
  },
};
