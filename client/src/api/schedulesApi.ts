// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * Schedules API Client
 * Handles all schedule-related API calls.
 */

import { apiClient } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import type { Schedule, CreateScheduleRequest, UpdateScheduleRequest, ScheduleListResponse } from "../types";

export const schedulesApi = {
  /**
   * List all schedules
   */
  async list(enabledOnly?: boolean): Promise<ScheduleListResponse> {
    const params = enabledOnly !== undefined ? { enabled: enabledOnly } : {};
    const response = await apiClient.get<ScheduleListResponse>(
      API_ENDPOINTS.SCHEDULES.LIST,
      { params }
    );
    return response.data;
  },

  /**
   * Get a specific schedule by ID
   */
  async get(scheduleId: string): Promise<Schedule> {
    const response = await apiClient.get<Schedule>(
      API_ENDPOINTS.SCHEDULES.GET(scheduleId)
    );
    return response.data;
  },

  /**
   * Create a new schedule
   */
  async create(request: CreateScheduleRequest): Promise<Schedule> {
    const response = await apiClient.post<Schedule>(
      API_ENDPOINTS.SCHEDULES.LIST,
      request
    );
    return response.data;
  },

  /**
   * Update an existing schedule
   */
  async update(
    scheduleId: string,
    request: UpdateScheduleRequest
  ): Promise<Schedule> {
    const response = await apiClient.put<Schedule>(
      API_ENDPOINTS.SCHEDULES.GET(scheduleId),
      request
    );
    return response.data;
  },

  /**
   * Delete a schedule
   */
  async delete(scheduleId: string): Promise<void> {
    await apiClient.delete(API_ENDPOINTS.SCHEDULES.GET(scheduleId));
  },

  /**
   * Toggle schedule enabled/disabled
   */
  async toggle(scheduleId: string): Promise<Schedule> {
    const response = await apiClient.post<Schedule>(
      API_ENDPOINTS.SCHEDULES.TOGGLE(scheduleId)
    );
    return response.data;
  },
};
