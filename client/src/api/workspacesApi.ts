// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Workspaces API Service - SAP workspace discovery and management.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import { Workspace } from "../types";

export interface WorkspaceListResponse {
  workspaces: Workspace[];
  count: number;
}

export interface WorkspaceDetailResponse extends Workspace {
  path?: string;
  scs_hosts?: string[];
  db_hosts?: string[];
}

export interface ListWorkspacesParams {
  sid?: string;
  env?: string;
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
};
