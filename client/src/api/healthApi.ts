// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Health API Service - Backend health check operations.
 */
import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import { HealthResponse } from "../types";

export const healthApi = {
  check: async (): Promise<HealthResponse> => {
    const response = await apiClient.get<HealthResponse>(API_ENDPOINTS.HEALTH);
    return response.data;
  },
};
