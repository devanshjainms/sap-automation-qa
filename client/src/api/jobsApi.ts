// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Jobs API Service - Async test execution job operations.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import { Job } from "../types";

export const jobsApi = {
  getStatus: async (jobId: string): Promise<Job> => {
    const response = await apiClient.get<Job>(API_ENDPOINTS.JOB_STATUS(jobId));
    return response.data;
  },

  getById: async (jobId: string): Promise<Job> => {
    const response = await apiClient.get<Job>(API_ENDPOINTS.JOB_BY_ID(jobId));
    return response.data;
  },

  list: async (params?: {
    conversationId?: string;
    status?: string;
  }): Promise<Job[]> => {
    const searchParams = new URLSearchParams();
    if (params?.conversationId) {
      searchParams.set("conversation_id", params.conversationId);
    }
    if (params?.status) {
      searchParams.set("status", params.status);
    }

    const query = searchParams.toString();
    const url = query ? `${API_ENDPOINTS.JOBS}?${query}` : API_ENDPOINTS.JOBS;

    const response = await apiClient.get<Job[]>(url);
    return response.data;
  },

  cancel: async (jobId: string): Promise<void> => {
    await apiClient.post(`${API_ENDPOINTS.JOB_BY_ID(jobId)}/cancel`);
  },
};
