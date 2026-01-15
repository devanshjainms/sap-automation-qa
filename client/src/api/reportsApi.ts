// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Reports API Client
 * API client for fetching test execution HTML reports.
 */

import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";

export interface ReportInfo {
  name: string;
  path: string;
  size: number;
  modified_at: string;
}

export interface ReportsListResponse {
  workspace_id: string;
  reports: ReportInfo[];
  quality_assurance_dir: string;
}

export const reportsApi = {
  /**
   * List all reports for a workspace
   */
  list: async (workspaceId: string): Promise<ReportsListResponse> => {
    const response = await apiClient.get<ReportsListResponse>(
      API_ENDPOINTS.WORKSPACE_REPORTS(workspaceId)
    );
    return response.data;
  },

  /**
   * Get URL for a specific report file
   */
  getReportUrl: (workspaceId: string, filePath: string): string => {
    return API_ENDPOINTS.WORKSPACE_REPORT_FILE(workspaceId, filePath);
  },
};
