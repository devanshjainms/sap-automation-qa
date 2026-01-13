// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Jobs API Service - Async job execution operations.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import { Job, JobListResponse } from "../types";

export interface JobListParams {
  workspaceId?: string;
  conversationId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export const jobsApi = {
  getStatus: async (jobId: string): Promise<Job> => {
    const response = await apiClient.get<Job>(API_ENDPOINTS.JOB_STATUS(jobId));
    return response.data;
  },

  getById: async (jobId: string): Promise<Job> => {
    const response = await apiClient.get<Job>(API_ENDPOINTS.JOB_BY_ID(jobId));
    return response.data;
  },

  list: async (params?: JobListParams): Promise<JobListResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.workspaceId) {
      searchParams.set("workspace_id", params.workspaceId);
    }
    if (params?.conversationId) {
      searchParams.set("conversation_id", params.conversationId);
    }
    if (params?.status) {
      searchParams.set("status", params.status);
    }
    if (params?.limit) {
      searchParams.set("limit", params.limit.toString());
    }
    if (params?.offset) {
      searchParams.set("offset", params.offset.toString());
    }

    const query = searchParams.toString();
    const url = query ? `${API_ENDPOINTS.JOBS}?${query}` : API_ENDPOINTS.JOBS;

    const response = await apiClient.get<JobListResponse>(url);
    return response.data;
  },

  listWorkspaces: async (): Promise<string[]> => {
    const response = await apiClient.get<string[]>(`${API_ENDPOINTS.JOBS}/workspaces/list`);
    return response.data;
  },

  cancel: async (jobId: string): Promise<void> => {
    await apiClient.post(`${API_ENDPOINTS.JOB_BY_ID(jobId)}/cancel`);
  },
};
